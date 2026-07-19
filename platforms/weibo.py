import html
import re

from ..models import BaseParser, OrderedContent, ParseContext, ParseResult


class WeiboParser(BaseParser):
    """解析微博状态、视频页、长文章和分享链接。"""

    name = "weibo"
    image_host_suffixes = ("sinaimg.cn", "sinaimg.com")
    STATUS_PATTERNS = (
        r"https?://(?:www\.)?weibo\.com/\d+/(?P<desktop_id>[0-9A-Za-z]+)",
        r"https?://m\.weibo\.cn/(?:status|detail|\d+)/(?P<mobile_id>[0-9A-Za-z]+)",
    )
    TV_PATTERN = (
        r"https?://(?:www\.)?weibo\.com/tv/show/\d{4}:\d+"
        r"\?[^\s#]*\bmid=(?P<mid>\d+)[^\s#]*"
    )
    VIDEO_PATTERN = (
        r"https?://video\.weibo\.com/show\?[^\s#]*"
        r"\bfid=(?P<fid>\d+:\d+)[^\s#]*"
    )
    SHARE_PATTERN = r"https?://mapp\.api\.weibo\.cn/fx/[A-Za-z0-9]+\.html"
    ARTICLE_PATTERNS = (
        r"https?://(?:www\.)?weibo\.com/ttarticle/[^\s#]*[?&#]id=(?P<article_query_id>\d+)",
        r"https?://card\.weibo\.com/article/[^\s#]*/id/(?P<article_path_id>\d+)",
    )
    PATTERNS = (
        *STATUS_PATTERNS,
        TV_PATTERN,
        VIDEO_PATTERN,
        SHARE_PATTERN,
        *ARTICLE_PATTERNS,
    )

    async def match(self, context: ParseContext) -> bool:
        return any(re.search(pattern, context.combined_text) for pattern in self.PATTERNS)

    async def parse(self, context: ParseContext) -> ParseResult:
        return ParseResult(platform=self.name, error="微博网络解析尚未完成。")

    @staticmethod
    def _base62_encode(number: int) -> str:
        """将非负整数编码为微博使用的 base62 字符串。"""
        if number < 0:
            raise ValueError("微博 mid 不能为负数")
        alphabet = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
        if number == 0:
            return "0"
        encoded = ""
        while number:
            number, remainder = divmod(number, 62)
            encoded = alphabet[remainder] + encoded
        return encoded

    @classmethod
    def _mid_to_bid(cls, mid: str) -> str:
        """把十进制微博 mid 按七位分块转换为 base62 短 ID。"""
        if not mid.isdigit():
            raise ValueError("微博 mid 格式无效")
        reversed_mid = mid[::-1]
        chunks = []
        for offset in range(0, len(reversed_mid), 7):
            decimal_chunk = reversed_mid[offset : offset + 7][::-1]
            encoded = cls._base62_encode(int(decimal_chunk))
            if offset + 7 < len(reversed_mid):
                encoded = encoded.zfill(4)
            chunks.append(encoded)
        return "".join(reversed(chunks))

    @staticmethod
    def _normalize_url(value: object) -> str:
        if not isinstance(value, str) or not value:
            return ""
        if value.startswith("//"):
            return f"https:{value}"
        return value if value.startswith(("http://", "https://")) else ""

    @staticmethod
    def _strip_html(value: object) -> str:
        if not isinstance(value, str):
            return ""
        text = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
        text = re.sub(r"</(?:p|div|li|blockquote)\s*>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "", text)
        text = html.unescape(text).replace("\u200b", "").replace("\xa0", " ")
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n[ \t]+", "\n", text)
        return re.sub(r"\n{3,}", "\n\n", text).strip()

    @classmethod
    def _select_video_url(cls, page_info: object) -> str:
        if not isinstance(page_info, dict):
            return ""
        urls = page_info.get("urls")
        if not isinstance(urls, dict):
            return ""
        for key in ("mp4_720p_mp4", "mp4_hd_mp4", "mp4_ld_mp4"):
            if url := cls._normalize_url(urls.get(key)):
                return url
        return ""

    @classmethod
    def _status_images(cls, status: dict) -> list[str]:
        pics = status.get("pics")
        if not isinstance(pics, list):
            return []
        image_urls = []
        for pic in pics:
            if not isinstance(pic, dict):
                continue
            large = pic.get("large")
            large_url = large.get("url") if isinstance(large, dict) else None
            if url := cls._normalize_url(large_url or pic.get("url")):
                image_urls.append(url)
        return image_urls

    @classmethod
    def _status_cover(cls, status: dict) -> str:
        page_info = status.get("page_info")
        if not isinstance(page_info, dict):
            return ""
        page_pic = page_info.get("page_pic")
        if not isinstance(page_pic, dict):
            return ""
        return cls._normalize_url(page_pic.get("url"))

    @classmethod
    def _append_status_content(
        cls,
        contents: list[OrderedContent],
        status: dict,
        text_prefix: str = "",
    ) -> None:
        text = cls._strip_html(status.get("text"))
        if text_prefix or text:
            value = "\n".join(part for part in (text_prefix, text) if part)
            if value:
                contents.append(OrderedContent(kind="text", value=value))
        contents.extend(
            OrderedContent(kind="image", value=url)
            for url in cls._status_images(status)
        )

    @classmethod
    def _parse_status_payload(cls, payload: dict) -> ParseResult:
        if not isinstance(payload, dict):
            raise ValueError("微博状态数据为空")
        user = payload.get("user")
        if not isinstance(user, dict) or not user.get("screen_name"):
            raise ValueError("微博作者数据为空")

        page_info = payload.get("page_info")
        page_info = page_info if isinstance(page_info, dict) else {}
        title = str(
            page_info.get("title")
            or payload.get("status_title")
            or "微博"
        )
        contents: list[OrderedContent] = []
        cls._append_status_content(contents, payload)

        video_url = cls._select_video_url(page_info)
        cover_url = cls._status_cover(payload)
        repost = payload.get("retweeted_status")
        if isinstance(repost, dict):
            repost_user = repost.get("user")
            repost_author = (
                str(repost_user.get("screen_name"))
                if isinstance(repost_user, dict) and repost_user.get("screen_name")
                else "未知作者"
            )
            cls._append_status_content(contents, repost, f"转发自 @{repost_author}")
            if not video_url:
                video_url = cls._select_video_url(repost.get("page_info"))
                cover_url = cls._status_cover(repost)

        return ParseResult(
            platform=cls.name,
            title=title,
            author=str(user["screen_name"]),
            cover_urls=[cover_url] if cover_url and video_url else [],
            video_url=video_url,
            ordered_contents=contents,
            extra_lines=[] if video_url or contents else ["未找到可发送的媒体。"],
        )
