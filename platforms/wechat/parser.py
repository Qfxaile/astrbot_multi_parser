"""路由并解析微信公众号文章与微信视频号分享链接。"""

import re

import httpx
from httpx import Cookies

from ...core.contracts import ParseContext, ParseResult
from ...core.http import cookie_config_value, parse_cookie_header
from ...core.parser import BaseParser
from .article import parse_article_html
from .channels import resolve_channels_share


class WeChatParser(BaseParser):
    """解析微信公众号文章和微信视频号作品。"""

    name = "wechat"
    display_name = "微信"
    cookie_config_key = "wechat_yuanbao_cookies"
    image_host_suffixes = (
        "qpic.cn",
        "qlogo.cn",
        "finder.video.qq.com",
    )
    ARTICLE_PATTERN = (
        r"https?://mp\.weixin\.qq\.com/s(?:"
        r"/[A-Za-z0-9_-]+(?:\?[^\s<>\"']*)?"
        r"|\?(?=[^\s<>\"']*__biz=)[^\s<>\"']+"
        r")"
    )
    CHANNELS_SHORT_PATTERN = (
        r"https?://weixin\.qq\.com/sph/[A-Za-z0-9_-]+"
        r"(?:\?[^\s<>\"']*)?"
    )
    CHANNELS_PREVIEW_PATTERN = (
        r"https?://channels\.weixin\.qq\.com/finder-preview/pages/"
        r"(?:sph|feed)\?[^\s<>\"']+"
    )

    async def match(self, context: ParseContext) -> bool:
        """判断消息中是否包含受支持的微信内容链接。"""
        text = context.combined_text
        return any(
            re.search(pattern, text)
            for pattern in (
                self.ARTICLE_PATTERN,
                self.CHANNELS_SHORT_PATTERN,
                self.CHANNELS_PREVIEW_PATTERN,
            )
        )

    async def parse(self, context: ParseContext) -> ParseResult:
        """按链接类型解析公众号文章或视频号作品。"""
        text = context.combined_text
        if match := re.search(self.ARTICLE_PATTERN, text):
            return await self._parse_article(self._clean_url(match.group(0)))
        for pattern in (
            self.CHANNELS_SHORT_PATTERN,
            self.CHANNELS_PREVIEW_PATTERN,
        ):
            if match := re.search(pattern, text):
                return await self._parse_channels(self._clean_url(match.group(0)))
        return ParseResult(platform=self.name, error="未找到受支持的微信链接。")

    async def _parse_article(self, url: str) -> ParseResult:
        headers = self._headers(url)
        async with httpx.AsyncClient(
            timeout=self.request_timeout,
            headers=headers,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            result = parse_article_html(response.text)
            return await self.materialize_images(result, client, url)

    async def _parse_channels(self, url: str) -> ParseResult:
        cookie_value = cookie_config_value(self.config, self.cookie_config_key)
        configured_values = dict(parse_cookie_header(cookie_value))
        user_id = configured_values.pop("yb_user_id", "")
        token = configured_values.pop("yb_token", "")
        yuanbao_credentials = (user_id, token) if user_id and token else None
        # 旧版手工 Cookie 继续绑定到元宝域；新令牌只按请求映射为认证头，
        # 不作为 Cookie 发送，也不会随客户端访问视频号域。
        cookies = Cookies()
        for name, value in configured_values.items():
            cookies.set(name, value, domain="yuanbao.tencent.com", path="/")
        async with httpx.AsyncClient(
            timeout=self.request_timeout,
            cookies=cookies,
        ) as client:
            result = await resolve_channels_share(
                client,
                url,
                credentials_configured=(
                    yuanbao_credentials is not None or bool(configured_values)
                ),
                yuanbao_credentials=yuanbao_credentials,
            )
            return await self.materialize_images(
                result,
                client,
                "https://channels.weixin.qq.com/",
            )

    @staticmethod
    def _headers(referer: str) -> dict[str, str]:
        return {
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": referer,
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        }

    @staticmethod
    def _clean_url(url: str) -> str:
        return url.rstrip(".,;，。；、)）]】")
