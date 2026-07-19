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
        """为解析结果构建消息组件。

        存在有序内容时，优先使用有序内容而不是旧版封面和图片 URL 列表。
        旧版图片错误使用其在 ``cover_urls + image_urls`` 合并序列中对应空槽位的索引。

        参数:
            include_video_url: 是否在摘要中包含视频 URL。
            include_summary: 是否包含标题、作者、简介、附加文本、错误信息和可选视频 URL。
            include_content: 是否包含有序内容或旧版媒体内容。

        返回:
            按所需渲染顺序排列的消息组件。
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

        # 有序内容用于图文混排，必须保持解析器生成的文本与图片先后关系。
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

        # 兼容旧版解析器：图片在前、摘要在后，失败槽位替换为对应错误文本。
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
        """下载图片 URL，并将原始字节编码为 base64 数据。

        有序内容优先于旧版封面和图片 URL 列表。图片 URL 必须使用 HTTP(S)、
        不包含用户信息、使用默认 HTTP(S) 端口，并匹配解析器配置的可信域名后缀。
        主机名只进行结构校验而不执行 DNS 解析；私有地址和不安全重定向会被拒绝。
        重定向最多手动跟随五次，每次请求前都会重新校验 Location。无效 URL
        与其他 HTTP 失败一样转换为图片失败槽位；无法解析主机名时使用
        已脱敏的 ``unknown`` 标识。

        参数:
            result: 包含旧版或有序图片槽位的解析结果。
            client: 当前 HTTP 客户端，复用其会话请求头和 Cookie。
            referer: 每次下载图片时发送的 Referer 请求头。

        返回:
            原解析结果对象，其中图片槽位已原地转换为实际数据。

        异常:
            Exception: 请求或处理图片时，除 ``httpx.HTTPError`` 和
                ``httpx.InvalidURL`` 之外的异常会原样向上传播。
        """
        image_number = 0
        # 新版解析器使用有序内容，图片下载失败时直接在原位置写入错误文本。
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
                            # 每一次重定向都重新执行完整校验，防止可信地址跳转到内网或非可信域名。
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
                            # 禁用客户端自动重定向，确保新的 Location 先经过安全校验。
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

        # 旧版解析器分别保存封面和图片，使用合并索引记录下载失败的槽位。
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
                            # 旧版字段与有序内容遵循相同的 URL 和重定向安全边界。
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
