import ipaddress
import mimetypes
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urljoin, urlparse
from uuid import uuid4

import httpx
from astrbot.api import logger

from .contracts import ParseResult


def mark_invalid_legacy_images(
    result: ParseResult,
    invalid_marker: str,
    *,
    error_detail: str = "InvalidURL",
) -> None:
    """将旧版图片列表中的无效候选转换为保持原索引的错误槽位。"""
    image_number = 0
    legacy_index = 0
    for field_name in ("cover_urls", "image_urls"):
        image_values = getattr(result, field_name)
        for field_index, image_url in enumerate(image_values):
            image_number += 1
            if image_url == invalid_marker:
                image_values[field_index] = ""
                result.image_errors[legacy_index] = (
                    f"第 {image_number} 张图片获取失败：{error_detail}"
                )
            legacy_index += 1


class ImageMaterializer:
    """安全地将解析结果中的远程图片流式写入临时文件。"""

    def __init__(
        self,
        config: Mapping[str, object],
        allowed_host_suffixes: tuple[str, ...] = (),
    ) -> None:
        self.config = config
        self.allowed_host_suffixes = allowed_host_suffixes

    async def materialize(
        self,
        result: ParseResult,
        client: httpx.AsyncClient,
        referer: str,
    ) -> ParseResult:
        image_number = 0
        try:
            if result.ordered_contents:
                for item in result.ordered_contents:
                    if item.kind not in {"image", "image_error"}:
                        continue
                    image_number += 1
                    if item.kind == "image_error" or not item.value:
                        continue
                    if item.value.startswith("base64://"):
                        continue
                    image_url = item.value
                    try:
                        image_path = await self._download_image(
                            client, image_url, referer
                        )
                        result.temporary_files.append(image_path)
                        item.value = str(image_path)
                    except (httpx.HTTPError, httpx.InvalidURL) as exc:
                        detail = self._image_error_detail(exc)
                        item.kind = "image_error"
                        item.value = f"第 {image_number} 张图片获取失败：{detail}"
                        logger.warning(
                            f"图片下载失败 ({self._hostname_label(image_url)}): {detail}"
                        )
                return result

            legacy_index = 0
            for field_name in ("cover_urls", "image_urls"):
                image_values = getattr(result, field_name)
                for field_index, image_url in enumerate(image_values):
                    image_number += 1
                    if not image_url or image_url.startswith("base64://"):
                        legacy_index += 1
                        continue
                    try:
                        image_path = await self._download_image(
                            client, image_url, referer
                        )
                        result.temporary_files.append(image_path)
                        image_values[field_index] = str(image_path)
                    except (httpx.HTTPError, httpx.InvalidURL) as exc:
                        image_values[field_index] = ""
                        detail = self._image_error_detail(exc)
                        result.image_errors[legacy_index] = (
                            f"第 {image_number} 张图片获取失败：{detail}"
                        )
                        logger.warning(
                            f"图片下载失败 ({self._hostname_label(image_url)}): {detail}"
                        )
                    legacy_index += 1
            return result
        except Exception:
            cleanup_temporary_files(result)
            raise

    async def _download_image(
        self,
        client: httpx.AsyncClient,
        image_url: str,
        referer: str,
    ) -> Path:
        current_url = image_url
        for redirect_count in range(6):
            self._validate_image_url(current_url)
            async with client.stream(
                "GET",
                current_url,
                headers={"Referer": referer},
                follow_redirects=False,
            ) as response:
                if 300 <= response.status_code < 400:
                    location = response.headers.get("Location")
                    if redirect_count >= 5 or not location:
                        raise httpx.InvalidURL("too many image redirects")
                    current_url = urljoin(current_url, location)
                    continue

                response.raise_for_status()
                image_path = self._new_image_path(
                    current_url, response.headers.get("Content-Type", "")
                )
                try:
                    with image_path.open("wb") as image_file:
                        async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                            image_file.write(chunk)
                except Exception:
                    image_path.unlink(missing_ok=True)
                    raise
                return image_path
        raise httpx.InvalidURL("too many image redirects")

    def _new_image_path(self, image_url: str, content_type: str) -> Path:
        configured_dir = self.config.get("image_temp_dir")
        temp_dir = (
            Path(str(configured_dir))
            if configured_dir
            else Path(__file__).resolve().parents[1] / "data" / "temp" / "images"
        )
        temp_dir.mkdir(parents=True, exist_ok=True)

        suffix = Path(urlparse(image_url).path).suffix.lower()
        allowed_suffixes = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}
        if suffix not in allowed_suffixes:
            media_type = content_type.split(";", 1)[0].strip().lower()
            suffix = mimetypes.guess_extension(media_type) or ".img"
            if suffix == ".jpe":
                suffix = ".jpg"
        return temp_dir / f"{uuid4().hex}{suffix}"

    def _validate_image_url(self, image_url: str) -> None:
        try:
            parsed_url = urlparse(image_url)
            hostname = parsed_url.hostname
            if (
                parsed_url.scheme not in {"http", "https"}
                or not hostname
                or parsed_url.username is not None
                or parsed_url.password is not None
                or (
                    self.allowed_host_suffixes
                    and not any(
                        hostname == suffix or hostname.endswith(f".{suffix}")
                        for suffix in self.allowed_host_suffixes
                    )
                )
            ):
                raise httpx.InvalidURL("unsafe image URL")
            try:
                port = parsed_url.port
            except ValueError as exc:
                raise httpx.InvalidURL("invalid image URL port") from exc
            if port not in {None, 80, 443}:
                raise httpx.InvalidURL("invalid image URL port")
            try:
                parsed_ip = ipaddress.ip_address(hostname)
            except ValueError:
                lowered_hostname = hostname.lower()
                if lowered_hostname == "localhost" or lowered_hostname.endswith(
                    (".localhost", ".local", ".internal")
                ):
                    raise httpx.InvalidURL("unsafe image hostname") from None
            else:
                if not parsed_ip.is_global:
                    raise httpx.InvalidURL("unsafe image IP")
        except ValueError as exc:
            raise httpx.InvalidURL("invalid image URL") from exc

    @staticmethod
    def _image_error_detail(exc: Exception) -> str:
        if isinstance(exc, httpx.HTTPStatusError):
            return f"HTTP {exc.response.status_code}"
        return type(exc).__name__

    @staticmethod
    def _hostname_label(image_url: str) -> str:
        try:
            return urlparse(image_url).hostname or "unknown"
        except ValueError:
            return "unknown"


def cleanup_temporary_files(result: ParseResult) -> None:
    """删除解析结果登记的临时文件，并始终清空登记列表。"""
    for path in result.temporary_files:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning(f"清理临时图片失败 ({path.name}): {exc}")
    result.temporary_files.clear()
