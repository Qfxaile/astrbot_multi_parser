import json
import re
from urllib.parse import quote, urlparse, urlsplit, urlunsplit

import httpx

from ..models import BaseParser, ParseContext, ParseResult


class RedBookParser(BaseParser):
    name = "redbook"
    image_host_suffixes = ("xhscdn.com", "xiaohongshu.com")
    INVALID_IMAGE_URL = "unsafe-image-url"
    PATTERN = (
        r"https?://(?:"
        r"www\.xiaohongshu\.com/(?:explore|discovery/item)/[^/?\s]+"
        r"|xhslink\.com(?:/[^/?\s]+)+"
        r")(?:\?[^\s#]*)?"
    )
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
            "Mobile/15E148 Safari/604.1"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"
        ),
        "Origin": "https://www.xiaohongshu.com",
    }

    async def match(self, context: ParseContext) -> bool:
        return bool(re.search(self.PATTERN, context.combined_text))

    async def parse(self, context: ParseContext) -> ParseResult:
        match = re.search(self.PATTERN, context.combined_text)
        if not match:
            return ParseResult(platform=self.name, error="未找到小红书链接。")

        cookies = httpx.Cookies()
        for item in str(self.config.get("redbook_cookies", "")).split(";"):
            if "=" in item:
                key, value = item.strip().split("=", 1)
                if key:
                    cookies.set(key, value, domain=".xiaohongshu.com", path="/")

        async with httpx.AsyncClient(
            timeout=int(self.config.get("request_timeout_seconds", 30)),
            follow_redirects=True,
            headers=self.HEADERS,
            cookies=cookies,
        ) as client:
            url = match.group(0)
            if (urlparse(url).hostname or "") == "xhslink.com":
                response = await client.get(url)
                response.raise_for_status()
                url = str(response.url)

            parsed_url = urlparse(url)
            note_match = re.search(
                r"/(?:explore|discovery/item)/(?P<note_id>[^/?]+)", parsed_url.path
            )
            if not note_match:
                raise ValueError("无法从小红书链接中提取笔记 ID")
            note_id = note_match.group("note_id")
            query = f"?{parsed_url.query}" if parsed_url.query else ""
            explore_url = f"https://www.xiaohongshu.com/explore/{note_id}{query}"
            discovery_url = (
                f"https://www.xiaohongshu.com/discovery/item/{note_id}{query}"
            )

            try:
                response = await client.get(explore_url)
                response.raise_for_status()
                state = self._extract_initial_state(response.text)
                result = self._parse_explore_state(state, note_id)
                content_url = explore_url
            except (httpx.HTTPError, ValueError, KeyError):
                response = await client.get(discovery_url)
                response.raise_for_status()
                state = self._extract_initial_state(response.text)
                result = self._parse_discovery_state(state)
                content_url = discovery_url
            parsed_content_url = urlsplit(content_url)
            image_referer = urlunsplit(
                parsed_content_url._replace(query="", fragment="")
            )
            image_number = 0
            legacy_index = 0
            for field_name in ("cover_urls", "image_urls"):
                image_values = getattr(result, field_name)
                for field_index, image_url in enumerate(image_values):
                    image_number += 1
                    if image_url == self.INVALID_IMAGE_URL:
                        image_values[field_index] = ""
                        result.image_errors[legacy_index] = (
                            f"第 {image_number} 张图片获取失败：InvalidURL"
                        )
                    legacy_index += 1
            return await self.materialize_images(result, client, image_referer)

    @staticmethod
    def _extract_initial_state(html: str) -> dict:
        matched = re.search(
            r"window\.__INITIAL_STATE__\s*=\s*(.*?)</script>",
            html,
            flags=re.DOTALL,
        )
        if not matched:
            raise ValueError("小红书分享链接失效或内容已删除")
        return json.loads(matched.group(1).strip().replace("undefined", "null"))

    def _parse_explore_state(self, state: dict, note_id: str) -> ParseResult:
        """Convert Xiaohongshu Explore state into a normalized result.

        Args:
            state: Decoded `window.__INITIAL_STATE__` object.
            note_id: Note identifier used as the map key.

        Returns:
            Parsed note metadata and media URLs.

        Raises:
            ValueError: If the note is absent from the page state.
        """
        note_root = state.get("note") if isinstance(state, dict) else None
        note_map = note_root.get("noteDetailMap") if isinstance(note_root, dict) else None
        note_entry = note_map.get(note_id) if isinstance(note_map, dict) else None
        note = note_entry.get("note") if isinstance(note_entry, dict) else None
        if not isinstance(note, dict) or not note:
            raise ValueError("小红书 Explore 页面中未找到笔记数据")
        image_urls = []
        image_list = note.get("imageList")
        if not isinstance(image_list, list):
            image_list = []
        for image in image_list:
            image_url = self._select_original_image_url(
                image, ("urlDefault", "url")
            )
            if image_url:
                image_urls.append(image_url)
        video_url = (
            self._select_video_url(note.get("video"))
            if note.get("type") == "video"
            else ""
        )
        return ParseResult(
            platform=self.name,
            title=str(note.get("title") or "无标题"),
            author=str(
                note["user"].get("nickname") or "未知作者"
                if isinstance(note.get("user"), dict)
                else "未知作者"
            ),
            description=str(note.get("desc") or ""),
            cover_urls=image_urls[:1] if video_url else [],
            image_urls=[] if video_url else image_urls,
            video_url=video_url,
            extra_lines=[] if video_url or image_urls else ["未找到可发送的媒体。"],
        )

    def _parse_discovery_state(self, state: dict) -> ParseResult:
        """Convert Xiaohongshu Discovery state into a normalized result.

        Args:
            state: Decoded `window.__INITIAL_STATE__` object.

        Returns:
            Parsed note metadata and media URLs.

        Raises:
            ValueError: If the fallback note data is absent.
        """
        note_data = state.get("noteData") if isinstance(state, dict) else None
        if not isinstance(note_data, dict):
            note_data = {}
        preload = note_data.get("normalNotePreloadData")
        if not isinstance(preload, dict):
            preload = {}
        data = note_data.get("data")
        note = data.get("noteData") if isinstance(data, dict) else None
        if not isinstance(note, dict) or not note:
            raise ValueError("小红书 Discovery 页面中未找到笔记数据")
        image_urls = []
        image_list = note.get("imageList")
        if not isinstance(image_list, list):
            image_list = []
        for image in image_list:
            image_url = self._select_original_image_url(
                image, ("urlDefault", "url")
            )
            if image_url:
                image_urls.append(image_url)
        video_url = (
            self._select_video_url(note.get("video"))
            if note.get("type") == "video"
            else ""
        )
        cover_urls = []
        if video_url:
            preload_images = preload.get("imagesList")
            if not isinstance(preload_images, list):
                preload_images = []
            for image in preload_images:
                image_url = self._select_original_image_url(
                    image, ("urlSizeLarge", "url")
                )
                if image_url:
                    cover_urls.append(image_url)
            cover_urls = cover_urls[:1] or image_urls[:1]
        return ParseResult(
            platform=self.name,
            title=str(note.get("title") or "无标题"),
            author=str(
                note["user"].get("nickName") or "未知作者"
                if isinstance(note.get("user"), dict)
                else "未知作者"
            ),
            description=str(note.get("desc") or ""),
            cover_urls=cover_urls,
            image_urls=[] if video_url else image_urls,
            video_url=video_url,
            extra_lines=[] if video_url or image_urls else ["未找到可发送的媒体。"],
        )

    @staticmethod
    def _select_video_url(video: object) -> str:
        """Select the preferred video stream from type-checked external data.

        Args:
            video: External video metadata that may contain malformed containers.

        Returns:
            The first non-empty master URL in codec priority order, or an empty
            string when no valid variant is available.
        """
        if not isinstance(video, dict):
            return ""
        media = video.get("media")
        if not isinstance(media, dict):
            return ""
        stream = media.get("stream")
        if not isinstance(stream, dict):
            return ""
        for codec in ("h265", "h264", "av1", "h266"):
            variants = stream.get(codec) or []
            if not isinstance(variants, list):
                continue
            for variant in variants:
                if not isinstance(variant, dict):
                    continue
                if isinstance(variant.get("masterUrl"), str) and variant["masterUrl"]:
                    return variant["masterUrl"]
        return ""

    @classmethod
    def _select_original_image_url(
        cls,
        image: object,
        fallback_fields: tuple[str, ...],
    ) -> str:
        """Select the first safe original image candidate in priority order.

        Args:
            image: External image metadata that may contain malformed values.
            fallback_fields: Ordered URL fields checked after file and trace IDs.

        Returns:
            A fixed-CDN ID URL, the first safe fallback URL, a locally rejected
            failure candidate when all supplied URLs are unsafe, or an empty string
            when no string candidate exists.
        """
        if not isinstance(image, dict):
            return ""
        for field_name in ("fileId", "traceId"):
            image_id = image.get(field_name)
            if isinstance(image_id, str) and image_id:
                path = f"/{quote(image_id.lstrip('/'), safe='/')}"
                return urlunsplit(
                    ("https", "sns-img-qc.xhscdn.com", path, "", "")
                )

        failure_candidate = ""
        for field_name in fallback_fields:
            candidate = image.get(field_name)
            if not isinstance(candidate, str) or not candidate:
                continue
            try:
                parsed = urlsplit(candidate)
                port = parsed.port
            except ValueError:
                failure_candidate = failure_candidate or candidate
                continue
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or port not in {None, 80, 443}
            ):
                failure_candidate = failure_candidate or cls.INVALID_IMAGE_URL
                continue
            return cls._strip_image_transform(candidate)
        return failure_candidate

    @staticmethod
    def _strip_image_transform(url: str) -> str:
        """Normalize a safe image URL without rewriting its authority.

        Args:
            url: Image URL whose path may end in a ``!<transform>`` suffix.

        Returns:
            URL with only the transform suffix removed, the original malformed
            value when httpx can reject it locally, or an invalid sentinel for
            unsafe schemes, credentials, hosts, and ports.
        """
        try:
            parsed = urlsplit(url)
        except ValueError:
            return url
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            return RedBookParser.INVALID_IMAGE_URL
        try:
            port = parsed.port
        except ValueError:
            return url
        if port not in {None, 80, 443}:
            return RedBookParser.INVALID_IMAGE_URL
        path = re.sub(r"![^/]*$", "", parsed.path)
        return urlunsplit(parsed._replace(path=path))
