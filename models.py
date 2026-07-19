import base64
import ipaddress
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urljoin, urlparse

import httpx

from astrbot.api import logger
from astrbot.api.message_components import Image, Plain, Video


@dataclass
class ParseContext:
    text: str
    json_urls: list[str] = field(default_factory=list)
    json_previews: list[str] = field(default_factory=list)

    @property
    def combined_text(self) -> str:
        return "\n".join([self.text, *self.json_urls]).strip()


@dataclass
class OrderedContent:
    kind: Literal["text", "image", "image_error"]
    value: str


@dataclass
class ParseResult:
    platform: str
    title: str = ""
    author: str = ""
    description: str = ""
    cover_urls: list[str] = field(default_factory=list)
    image_urls: list[str] = field(default_factory=list)
    video_url: str = ""
    error: str = ""
    extra_lines: list[str] = field(default_factory=list)
    ordered_contents: list[OrderedContent] = field(default_factory=list)
    image_errors: dict[int, str] = field(default_factory=dict)

    @property
    def image_count(self) -> int:
        return (
            len(self.cover_urls)
            + len(self.image_urls)
            + sum(
                item.kind in {"image", "image_error"}
                for item in self.ordered_contents
            )
        )

    def info_chain(
        self,
        include_video_url: bool = False,
        include_summary: bool = True,
        include_content: bool = True,
    ) -> list:
        """Build message components for the parse result.

        When ordered content exists, it takes priority over legacy cover and image
        URL lists. Legacy image errors use the index of the corresponding empty
        slot in the combined ``cover_urls + image_urls`` sequence.

        Args:
            include_video_url: Whether to include the video URL in the summary.
            include_summary: Whether to include title, author, description, extra
                lines, errors, and the optional video URL.
            include_content: Whether to include ordered content or legacy media.

        Returns:
            Message components in their required rendering order.
        """
        summary_chain: list = []
        lines = []
        if include_summary:
            if self.title:
                lines.append(self.title)
            if self.author:
                lines.append(f"作者: {self.author}")
            if self.description:
                lines.append(f"简介:\n{self.description}")
            lines.extend(self.extra_lines)
            if self.error:
                lines.append(self.error)
            if self.video_url and include_video_url:
                lines.append(f"视频链接: {self.video_url}")

            if lines:
                summary_chain.append(Plain("\n".join(lines)))

        if self.ordered_contents:
            content_chain: list = []
            if include_content:
                for item in self.ordered_contents:
                    if not item.value:
                        continue
                    if item.kind == "image":
                        content_chain.append(Image(file=item.value))
                    else:
                        content_chain.append(Plain(item.value))
            return [*summary_chain, *content_chain]

        content_chain: list = []
        if include_content:
            for index, image_url in enumerate([*self.cover_urls, *self.image_urls]):
                if image_url:
                    content_chain.append(Image(file=image_url))
                elif error := self.image_errors.get(index):
                    content_chain.append(Plain(error))
        return [*content_chain, *summary_chain]

    def video_chain(self) -> list:
        return [Video.fromURL(self.video_url)] if self.video_url else []


class BaseParser:
    name = "base"
    image_host_suffixes: tuple[str, ...] = ()

    def __init__(self, config):
        self.config = config

    async def match(self, context: ParseContext) -> bool:
        raise NotImplementedError

    async def parse(self, context: ParseContext) -> ParseResult:
        raise NotImplementedError

    async def materialize_images(
        self,
        result: ParseResult,
        client: httpx.AsyncClient,
        referer: str,
    ) -> ParseResult:
        """Download image URLs into their original base64-encoded bytes.

        Ordered content takes priority over legacy cover and image URL lists. An
        image URL must use HTTP(S), omit userinfo, use a default HTTP(S) port,
        and match the parser's trusted host suffixes. Hostnames are checked
        structurally without DNS resolution; private addresses and unsafe
        redirects are rejected. Redirects are followed manually for at most
        five hops, revalidating every Location before requesting it. An invalid
        URL is converted to the same failed image slot as other HTTP failures,
        with a sanitized ``unknown`` hostname when it cannot be parsed.

        Args:
            result: Parse result containing legacy or ordered image slots.
            client: Active HTTP client whose session headers and cookies are reused.
            referer: Referer header sent with every image download.

        Returns:
            The same parse result with image slots materialized in place.

        Raises:
            Exception: Any exception other than ``httpx.HTTPError`` and
                ``httpx.InvalidURL`` raised while requesting or processing an
                image is propagated unchanged.
        """
        image_number = 0
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
                hostname = "unknown"
                try:
                    current_url = image_url
                    for redirect_count in range(6):
                        hostname = "unknown"
                        try:
                            parsed_url = urlparse(current_url)
                            hostname = parsed_url.hostname
                            if (
                                parsed_url.scheme not in {"http", "https"}
                                or not hostname
                                or parsed_url.username is not None
                                or parsed_url.password is not None
                                or (
                                    self.image_host_suffixes
                                    and not any(
                                        hostname == suffix
                                        or hostname.endswith(f".{suffix}")
                                        for suffix in self.image_host_suffixes
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
                                    raise httpx.InvalidURL("unsafe image hostname")
                            else:
                                if not parsed_ip.is_global:
                                    raise httpx.InvalidURL("unsafe image IP")
                        except ValueError as exc:
                            raise httpx.InvalidURL("invalid image URL") from exc
                        response = await client.get(
                            current_url,
                            headers={"Referer": referer},
                            follow_redirects=False,
                        )
                        if 300 <= response.status_code < 400:
                            location = response.headers.get("Location")
                            if redirect_count >= 5 or not location:
                                raise httpx.InvalidURL("too many image redirects")
                            current_url = urljoin(current_url, location)
                            continue
                        response.raise_for_status()
                        encoded_image = base64.b64encode(response.content).decode()
                        item.value = f"base64://{encoded_image}"
                        break
                except (httpx.HTTPError, httpx.InvalidURL) as exc:
                    detail = (
                        f"HTTP {exc.response.status_code}"
                        if isinstance(exc, httpx.HTTPStatusError)
                        else type(exc).__name__
                    )
                    item.kind = "image_error"
                    item.value = f"第 {image_number} 张图片获取失败：{detail}"
                    logger.warning(f"图片下载失败 ({hostname}): {detail}")
            return result

        legacy_index = 0
        for field_name in ("cover_urls", "image_urls"):
            image_values = getattr(result, field_name)
            for field_index, image_url in enumerate(image_values):
                image_number += 1
                if not image_url or image_url.startswith("base64://"):
                    legacy_index += 1
                    continue
                hostname = "unknown"
                try:
                    current_url = image_url
                    for redirect_count in range(6):
                        hostname = "unknown"
                        try:
                            parsed_url = urlparse(current_url)
                            hostname = parsed_url.hostname
                            if (
                                parsed_url.scheme not in {"http", "https"}
                                or not hostname
                                or parsed_url.username is not None
                                or parsed_url.password is not None
                                or (
                                    self.image_host_suffixes
                                    and not any(
                                        hostname == suffix
                                        or hostname.endswith(f".{suffix}")
                                        for suffix in self.image_host_suffixes
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
                                    raise httpx.InvalidURL("unsafe image hostname")
                            else:
                                if not parsed_ip.is_global:
                                    raise httpx.InvalidURL("unsafe image IP")
                        except ValueError as exc:
                            raise httpx.InvalidURL("invalid image URL") from exc
                        response = await client.get(
                            current_url,
                            headers={"Referer": referer},
                            follow_redirects=False,
                        )
                        if 300 <= response.status_code < 400:
                            location = response.headers.get("Location")
                            if redirect_count >= 5 or not location:
                                raise httpx.InvalidURL("too many image redirects")
                            current_url = urljoin(current_url, location)
                            continue
                        response.raise_for_status()
                        encoded_image = base64.b64encode(response.content).decode()
                        image_values[field_index] = f"base64://{encoded_image}"
                        break
                except (httpx.HTTPError, httpx.InvalidURL) as exc:
                    image_values[field_index] = ""
                    detail = (
                        f"HTTP {exc.response.status_code}"
                        if isinstance(exc, httpx.HTTPStatusError)
                        else type(exc).__name__
                    )
                    result.image_errors[legacy_index] = (
                        f"第 {image_number} 张图片获取失败：{detail}"
                    )
                    logger.warning(f"图片下载失败 ({hostname}): {detail}")
                legacy_index += 1
        return result
