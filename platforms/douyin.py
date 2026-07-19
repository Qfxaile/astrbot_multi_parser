import json
import re
from urllib.parse import parse_qs, urlparse, urlsplit

import httpx

from ..models import BaseParser, ParseContext, ParseResult


class DouyinParser(BaseParser):
    name = "douyin"
    image_host_suffixes = (
        "douyinpic.com",
        "byteimg.com",
        "pstatp.com",
        "douyincdn.com",
        "bytedance.com",
    )
    INVALID_IMAGE_URL = "unsafe-image-url"
    PATTERN = (
        r"https?://(?:"
        r"(?:v|jx)\.douyin\.com/[A-Za-z0-9_-]+"
        r"|(?:www|m)\.douyin\.com/(?:video|note)/\d+[^\s]*"
        r"|(?:www\.)?iesdouyin\.com/share/(?:slides|video|note)/\d+[^\s]*"
        r"|jingxuan\.douyin\.com/m/(?:slides|video|note)/\d+[^\s]*"
        r")"
    )
    PLAY_RATIOS = ("1080p", "720p", "540p", "360p")
    TTWID_REGISTER_URL = "https://ttwid.bytedance.com/ttwid/union/register/"
    SLIDES_URL = "https://www.iesdouyin.com/web/api/v2/aweme/slidesinfo/"
    IOS_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
            "Mobile/15E148 Safari/604.1"
        ),
        "Accept": "text/html,application/xhtml+xml,application/json,*/*",
    }

    async def match(self, context: ParseContext) -> bool:
        return bool(re.search(self.PATTERN, context.combined_text))

    async def parse(self, context: ParseContext) -> ParseResult:
        match = re.search(self.PATTERN, context.combined_text)
        if not match:
            return ParseResult(platform=self.name, error="未找到大陆抖音链接。")

        cookies = httpx.Cookies()
        for item in str(self.config.get("douyin_cookies", "")).split(";"):
            if "=" in item:
                key, value = item.strip().split("=", 1)
                if key:
                    cookies.set(key, value, domain=".douyin.com", path="/")
                    cookies.set(key, value, domain=".iesdouyin.com", path="/")

        timeout = int(self.config.get("request_timeout_seconds", 30))
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers=self.IOS_HEADERS,
            cookies=cookies,
        ) as client:
            url = match.group(0)
            hostname = urlparse(url).hostname or ""
            if hostname in {"v.douyin.com", "jx.douyin.com"}:
                response = await client.get(url)
                response.raise_for_status()
                url = str(response.url)

            work_match = re.search(
                r"/(?:share/|m/)?(?P<type>slides|video|note)/(?P<id>\d+)", url
            )
            if not work_match:
                query = parse_qs(urlparse(url).query)
                work_id = (query.get("aweme_id") or [""])[0]
                work_type = "video"
            else:
                work_id = work_match.group("id")
                work_type = work_match.group("type")
            if not work_id:
                raise ValueError("无法从抖音链接中提取作品 ID")

            if work_type == "slides":
                response = await client.get(
                    self.SLIDES_URL,
                    params={"aweme_ids": f"[{work_id}]", "request_source": "200"},
                )
                response.raise_for_status()
                result = self._parse_slides_data(response.json())
                share_url = f"https://www.iesdouyin.com/share/{work_type}/{work_id}/"
            else:
                await self._ensure_ttwid(client)
                share_url = f"https://www.iesdouyin.com/share/{work_type}/{work_id}/"
                response = await client.get(share_url, headers={"Referer": share_url})
                response.raise_for_status()
                router_data = self._extract_router_data(response.text)
                result = self._parse_router_data(router_data)

                play_token = ""
                retained_lines = []
                for line in result.extra_lines:
                    if line.startswith("play_token="):
                        play_token = line.removeprefix("play_token=")
                    else:
                        retained_lines.append(line)
                result.extra_lines = retained_lines
                if play_token:
                    probed_url = await self._probe_video_url(
                        client, play_token, share_url
                    )
                    if probed_url:
                        result.video_url = probed_url

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
            return await self.materialize_images(result, client, share_url)

    @staticmethod
    def _extract_router_data(html: str) -> dict:
        matched = re.search(
            r"window\._ROUTER_DATA\s*=\s*(.*?)</script>", html, flags=re.DOTALL
        )
        if not matched:
            raise ValueError("抖音分享页中未找到 _ROUTER_DATA")
        return json.loads(matched.group(1).strip())

    def _parse_router_data(self, data: dict) -> ParseResult:
        """Convert Douyin router data into a normalized result.

        Args:
            data: Decoded `window._ROUTER_DATA` object.

        Returns:
            Parsed metadata and media candidates.

        Raises:
            ValueError: If no video or note page is present.
        """
        loader_data = data.get("loaderData", {}) if isinstance(data, dict) else {}
        if not isinstance(loader_data, dict):
            loader_data = {}
        page = next(
            (
                value
                for key, value in loader_data.items()
                if isinstance(key, str)
                and isinstance(value, dict)
                and key.startswith(("video_", "note_"))
                and key.endswith("/page")
            ),
            None,
        )
        video_info = (page or {}).get("videoInfoRes", {})
        if not isinstance(video_info, dict):
            video_info = {}
        items = video_info.get("item_list", [])
        if not isinstance(items, list):
            items = []
        item = next((value for value in items if isinstance(value, dict)), None)
        if item is None:
            raise ValueError("抖音分享页中未找到作品数据")
        author_data = item.get("author")
        author = str(
            author_data.get("nickname")
            if isinstance(author_data, dict) and author_data.get("nickname")
            else "未知作者"
        )
        title = str(item.get("desc") or "未知标题")
        images = item.get("images") or []
        if not isinstance(images, list):
            images = []
        image_urls = []
        for image in images:
            image_url = self._select_image_url(image)
            if image_url:
                image_urls.append(image_url)
        if image_urls:
            return ParseResult(
                platform=self.name,
                title=title,
                author=author,
                image_urls=image_urls,
            )

        video = item.get("video")
        if not isinstance(video, dict):
            video = {}
        play_addr = video.get("play_addr")
        if not isinstance(play_addr, dict):
            play_addr = {}
        fallback_urls = play_addr.get("url_list") or []
        if not isinstance(fallback_urls, list):
            fallback_urls = []
        fallback_urls = [url for url in fallback_urls if isinstance(url, str) and url]
        fallback_url = (
            fallback_urls[0].replace("playwm", "play") if fallback_urls else ""
        )
        cover_url = self._select_image_url(video.get("cover"))
        play_token = str(play_addr.get("uri") or "")
        if not play_token:
            for video_url in fallback_urls:
                query = parse_qs(urlparse(str(video_url)).query)
                if query.get("video_id"):
                    play_token = query["video_id"][0]
                    break
        extra_lines = [f"play_token={play_token}"] if play_token else []
        if not fallback_url and not play_token:
            extra_lines.append("无法获取视频直链。")
        return ParseResult(
            platform=self.name,
            title=title,
            author=author,
            cover_urls=[cover_url] if cover_url else [],
            video_url=fallback_url,
            extra_lines=extra_lines,
        )

    def _parse_slides_data(self, data: dict) -> ParseResult:
        details = data.get("aweme_details") if isinstance(data, dict) else []
        if not isinstance(details, list):
            details = []
        item = next((value for value in details if isinstance(value, dict)), None)
        if item is None:
            raise ValueError("抖音 Slides 数据为空")
        images = item.get("images") or []
        if not isinstance(images, list):
            images = []
        image_urls = []
        for image in images:
            image_url = self._select_image_url(image)
            if image_url:
                image_urls.append(image_url)
        if not image_urls:
            raise ValueError("抖音 Slides 中未找到图片")
        return ParseResult(
            platform=self.name,
            title=str(item.get("desc") or "未知标题"),
            author=str(
                item["author"].get("nickname") or "未知作者"
                if isinstance(item.get("author"), dict)
                else "未知作者"
            ),
            image_urls=image_urls,
        )

    @classmethod
    def _select_image_url(cls, image: object) -> str:
        """Select and validate an image candidate without iterating bad containers.

        Args:
            image: External image object containing download or display URL lists.

        Returns:
            The first non-empty candidate, an invalid sentinel for unsafe URLs, or
            an empty string when the object has no string candidate.
        """
        if not isinstance(image, dict):
            return ""
        failure_candidate = ""
        for field_name in ("download_url_list", "url_list"):
            candidates = image.get(field_name)
            if not isinstance(candidates, list):
                continue
            for candidate in candidates:
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
                return candidate
        return failure_candidate

    async def _ensure_ttwid(self, client: httpx.AsyncClient):
        if any(cookie.name == "ttwid" for cookie in client.cookies.jar):
            return
        response = await client.post(
            self.TTWID_REGISTER_URL,
            headers={
                "Content-Type": "application/json",
                "Referer": "https://www.iesdouyin.com/",
            },
            json={
                "region": "cn",
                "aid": 1768,
                "needFid": False,
                "service": "www.iesdouyin.com",
                "union": True,
                "fid": "",
            },
        )
        response.raise_for_status()
        body = response.json()
        if callback_url := body.get("redirect_url"):
            callback = await client.get(
                callback_url,
                headers={"Referer": "https://www.iesdouyin.com/"},
            )
            callback.raise_for_status()
        if not any(cookie.name == "ttwid" for cookie in client.cookies.jar):
            raise ValueError("抖音匿名 ttwid 注册失败")

    async def _probe_video_url(
        self,
        client: httpx.AsyncClient,
        video_id: str,
        referer: str,
    ) -> str:
        candidates: list[tuple[int, str]] = []
        for ratio in self.PLAY_RATIOS:
            try:
                response = await client.get(
                    "https://aweme.snssdk.com/aweme/v1/play/",
                    params={"video_id": video_id, "ratio": ratio},
                    headers={"Range": "bytes=0-1", "Referer": referer},
                )
                if response.status_code >= 400:
                    continue
                size = self._extract_response_size(response.headers)
                if size > 0:
                    candidates.append((size, str(response.url)))
            except httpx.HTTPError:
                continue
        return max(candidates, default=(0, ""), key=lambda item: item[0])[1]

    @staticmethod
    def _extract_response_size(headers: httpx.Headers) -> int:
        if content_range := headers.get("Content-Range"):
            if matched := re.search(r"/(\d+)\s*$", content_range):
                return int(matched.group(1))
        content_length = headers.get("Content-Length", "")
        return int(content_length) if content_length.isdigit() else 0
