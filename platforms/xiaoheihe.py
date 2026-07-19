from __future__ import annotations

import hashlib
import html
import json
import random
import re
import time
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit

import httpx

from ..models import BaseParser, OrderedContent, ParseContext, ParseResult


class _PostHTMLParser(HTMLParser):
    """按小黑盒正文片段的可见顺序提取文本和图片候选。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.contents: list[OrderedContent] = []
        self._text_parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        if tag in {"script", "style", "noscript"}:
            self._ignored_depth += 1
            return
        if self._ignored_depth:
            return
        if tag in {"p", "div", "li", "blockquote", "br"}:
            self._flush_text()
        if tag == "img":
            self._flush_text()
            attributes = dict(attrs)
            image_url = str(
                attributes.get("data-original")
                or attributes.get("data-src")
                or attributes.get("src")
                or ""
            )
            if image_url:
                self.contents.append(OrderedContent(kind="image", value=image_url))

    def handle_endtag(self, tag: str):
        if tag in {"script", "style", "noscript"}:
            if self._ignored_depth:
                self._ignored_depth -= 1
            return
        if not self._ignored_depth and tag in {"p", "div", "li", "blockquote"}:
            self._flush_text()

    def handle_data(self, data: str):
        if not self._ignored_depth and (text := data.strip()):
            self._text_parts.append(text)

    def close(self):
        super().close()
        self._flush_text()

    def _flush_text(self):
        text = " ".join(self._text_parts).strip()
        self._text_parts.clear()
        if text:
            self.contents.append(OrderedContent(kind="text", value=text))


class XiaoheiheParser(BaseParser):
    """解析小黑盒社区帖子和游戏详情。"""

    name = "xiaoheihe"
    image_host_suffixes = ("max-c.com", "xiaoheihe.cn")
    CHAR_TABLE = "AB45STUVWZEFGJ6CH01D237IXYPQRKLMN89"
    BBS_WEB_PATTERN = (
        r"https?://(?:www\.)?xiaoheihe\.cn/app/bbs/link/"
        r"(?P<link_id>[0-9a-z]+)"
    )
    BBS_SHARE_PATTERN = (
        r"https?://api\.xiaoheihe\.cn/v3/bbs/app/api/(?:web/)?share"
        r"\?[^\s#]*\blink_id=(?P<share_link_id>[0-9a-z]+)[^\s#]*"
    )
    GAME_WEB_PATTERN = (
        r"https?://(?:www\.)?xiaoheihe\.cn/app/topic/game/"
        r"(?P<game_type>[a-z]+)/(?P<appid>[0-9a-z]+)"
    )
    GAME_SHARE_PATTERN = (
        r"https?://api\.xiaoheihe\.cn/game/share_game_detail\?[^\s#]*"
        r"\bappid=(?P<share_appid>[0-9a-z]+)[^\s#]*"
        r"\bgame_type=(?P<share_game_type>[a-z]+)[^\s#]*"
    )
    PATTERNS = (
        BBS_WEB_PATTERN,
        BBS_SHARE_PATTERN,
        GAME_WEB_PATTERN,
        GAME_SHARE_PATTERN,
    )
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.xiaoheihe.cn/",
        "Origin": "https://www.xiaoheihe.cn",
    }

    async def match(self, context: ParseContext) -> bool:
        return any(re.search(pattern, context.combined_text) for pattern in self.PATTERNS)

    async def parse(self, context: ParseContext) -> ParseResult:
        text = context.combined_text
        for pattern in (self.BBS_WEB_PATTERN, self.BBS_SHARE_PATTERN):
            if match := re.search(pattern, text):
                link_id = match.groupdict().get("link_id") or match.groupdict().get(
                    "share_link_id"
                )
                return await self._parse_post_by_id(str(link_id))
        if any(re.search(pattern, text) for pattern in (self.GAME_WEB_PATTERN, self.GAME_SHARE_PATTERN)):
            return ParseResult(platform=self.name, error="小黑盒游戏解析尚未完成。")
        return ParseResult(platform=self.name, error="未找到小黑盒链接。")

    def _timeout(self) -> float:
        return float(self.config.get("request_timeout_seconds", 30))

    def _extract_xhh_tokenid_from_cookies(self) -> str | None:
        cookie_header = str(self.config.get("xiaoheihe_cookies", ""))
        matched = re.search(r"(?:^|;\s*)x_xhh_tokenid=([^;]+)", cookie_header)
        return matched.group(1) if matched else None

    async def _build_request_context(self) -> dict[str, str]:
        token = self._extract_xhh_tokenid_from_cookies()
        if not token:
            raise ValueError("获取小黑盒 x_xhh_tokenid 失败，请配置小黑盒 Cookies")
        return {
            "x_xhh_tokenid": token,
            "device_id": token[1:] if token.startswith("B") else "",
        }

    async def _parse_post_by_id(self, link_id: str) -> ParseResult:
        request_context = await self._build_request_context()
        params = {
            "os_type": "web",
            "app": "heybox",
            "client_type": "web",
            "version": "999.0.4",
            "web_version": "2.5",
            "x_client_type": "web",
            "x_app": "heybox_website",
            "heybox_id": "",
            "x_os_type": "Windows",
            "device_info": "Chrome",
            "device_id": request_context["device_id"],
            "link_id": link_id,
            "owner_only": "1",
            **self._sign_path("/bbs/app/link/tree"),
        }
        referer = f"https://www.xiaoheihe.cn/app/bbs/link/{link_id}"
        async with httpx.AsyncClient(
            timeout=self._timeout(),
            follow_redirects=False,
            headers=self.HEADERS,
        ) as client:
            response = await client.get(
                "https://api.xiaoheihe.cn/bbs/app/link/tree",
                params=params,
                headers={
                    "Cookie": (
                        "x_xhh_tokenid="
                        f"{request_context['x_xhh_tokenid']}"
                    )
                },
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or payload.get("status") != "ok":
                raise ValueError("小黑盒 link/tree 请求失败")
            result_root = payload.get("result")
            if not isinstance(result_root, dict):
                raise ValueError("小黑盒 link/tree 结果为空")
            result = self._parse_post_payload(result_root)
            return await self.materialize_images(result, client, referer)

    @classmethod
    def _parse_post_payload(cls, payload: object) -> ParseResult:
        link = payload.get("link") if isinstance(payload, dict) else None
        if not isinstance(link, dict):
            raise ValueError("小黑盒 link/tree 缺少 link 节点")
        user = link.get("user")
        author = "未知作者"
        if isinstance(user, dict):
            author = cls._clean_text(
                str(user.get("username") or user.get("nickname") or "")
            ) or author
        contents = cls._parse_post_contents(link.get("text"))
        video_url = cls._normalize_media_url(link.get("video_url"))
        if not link.get("has_video"):
            video_url = ""
        return ParseResult(
            platform=cls.name,
            title=cls._clean_text(str(link.get("title") or "")) or "小黑盒帖子",
            author=author,
            description=cls._clean_text(str(link.get("description") or "")),
            video_url=video_url,
            ordered_contents=contents,
            extra_lines=[] if contents or video_url else ["未找到可发送的媒体。"],
        )

    @classmethod
    def _parse_post_contents(cls, raw_text: object) -> list[OrderedContent]:
        if not isinstance(raw_text, str) or not raw_text.strip():
            return []
        try:
            blocks = json.loads(raw_text)
        except json.JSONDecodeError:
            text = cls._clean_text(raw_text)
            return [OrderedContent(kind="text", value=text)] if text else []
        if not isinstance(blocks, list):
            text = cls._clean_text(raw_text)
            return [OrderedContent(kind="text", value=text)] if text else []

        contents: list[OrderedContent] = []
        seen_images: set[str] = set()
        for block in blocks:
            if not isinstance(block, dict):
                continue
            if str(block.get("type") or "") == "img":
                cls._append_image(contents, seen_images, block.get("url"))
                continue
            fragment = str(block.get("text") or "")
            if not fragment:
                continue
            parser = _PostHTMLParser()
            parser.feed(fragment)
            parser.close()
            for item in parser.contents:
                if item.kind == "image":
                    cls._append_image(contents, seen_images, item.value)
                elif value := cls._clean_text(item.value):
                    contents.append(OrderedContent(kind="text", value=value))
        return contents

    @classmethod
    def _append_image(
        cls,
        contents: list[OrderedContent],
        seen_images: set[str],
        candidate: object,
    ) -> None:
        image_url = cls._normalize_image_url(candidate)
        image_key = cls._image_dedup_key(image_url)
        if image_url and image_key and image_key not in seen_images:
            seen_images.add(image_key)
            contents.append(OrderedContent(kind="image", value=image_url))

    @staticmethod
    def _clean_text(text: str) -> str:
        value = html.unescape(text.replace("\xa0", " "))
        value = re.sub(r"[ \t\r\f\v]+", " ", value)
        value = re.sub(r"\n{3,}", "\n\n", value)
        return value.strip()

    @staticmethod
    def _normalize_media_url(value: object) -> str:
        if not isinstance(value, str) or not value:
            return ""
        normalized = html.unescape(value).strip()
        if normalized.startswith("//"):
            normalized = f"https:{normalized}"
        return normalized if normalized.startswith(("http://", "https://")) else ""

    @classmethod
    def _normalize_image_url(cls, value: object) -> str:
        normalized = cls._normalize_media_url(value)
        if not normalized:
            return ""
        try:
            parsed = urlsplit(normalized)
        except ValueError:
            return normalized
        hostname = (parsed.hostname or "").lower()
        if hostname == "imgheybox1.max-c.com":
            parsed = parsed._replace(netloc="imgheybox.max-c.com")
        return urlunsplit(parsed)

    @staticmethod
    def _image_dedup_key(url: str) -> str:
        if not url:
            return ""
        return url.split("?", 1)[0].replace(
            "imgheybox1.max-c.com", "imgheybox.max-c.com"
        )

    def _sign_path(self, path: str) -> dict[str, str | int]:
        now = int(time.time())
        nonce = hashlib.md5(
            (str(now) + str(random.random())).encode()
        ).hexdigest().upper()
        return {
            "hkey": self._ov(path, now + 1, nonce),
            "_time": now,
            "nonce": nonce,
        }

    def _ov(self, path: str, timestamp: int, nonce: str) -> str:
        normalized_path = "/" + "/".join(
            part for part in path.split("/") if part
        ) + "/"
        interleaved = self._interleave(
            [
                self._av(str(timestamp), -2),
                self._sv(normalized_path),
                self._sv(nonce),
            ]
        )[:20]
        digest = hashlib.md5(interleaved.encode()).hexdigest()
        prefix = self._av(digest[:5], -4)
        suffix = str(
            sum(self._mix_columns([ord(character) for character in digest[-6:]]))
            % 100
        ).zfill(2)
        return prefix + suffix

    def _av(self, text: str, cut: int) -> str:
        table = self.CHAR_TABLE[:cut]
        return "".join(table[ord(character) % len(table)] for character in text)

    def _sv(self, text: str) -> str:
        return "".join(
            self.CHAR_TABLE[ord(character) % len(self.CHAR_TABLE)]
            for character in text
        )

    @staticmethod
    def _interleave(parts: list[str]) -> str:
        result = []
        for index in range(max(len(part) for part in parts)):
            for part in parts:
                if index < len(part):
                    result.append(part[index])
        return "".join(result)

    @staticmethod
    def _xtime(value: int) -> int:
        return ((value << 1) ^ 27) & 0xFF if value & 128 else value << 1

    @classmethod
    def _mul3(cls, value: int) -> int:
        return cls._xtime(value) ^ value

    @classmethod
    def _mul6(cls, value: int) -> int:
        return cls._mul3(cls._xtime(value))

    @classmethod
    def _mul12(cls, value: int) -> int:
        return cls._mul6(cls._mul3(cls._xtime(value)))

    @classmethod
    def _mul14(cls, value: int) -> int:
        return cls._mul12(value) ^ cls._mul6(value) ^ cls._mul3(value)

    @classmethod
    def _mix_columns(cls, column: list[int]) -> list[int]:
        values = list(column)
        while len(values) < 4:
            values.append(0)
        mixed = [
            cls._mul14(values[0])
            ^ cls._mul12(values[1])
            ^ cls._mul6(values[2])
            ^ cls._mul3(values[3]),
            cls._mul3(values[0])
            ^ cls._mul14(values[1])
            ^ cls._mul12(values[2])
            ^ cls._mul6(values[3]),
            cls._mul6(values[0])
            ^ cls._mul3(values[1])
            ^ cls._mul14(values[2])
            ^ cls._mul12(values[3]),
            cls._mul12(values[0])
            ^ cls._mul6(values[1])
            ^ cls._mul3(values[2])
            ^ cls._mul14(values[3]),
        ]
        if len(values) > 4:
            mixed.extend(values[4:])
        return mixed
