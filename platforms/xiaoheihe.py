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
        if match := re.search(self.GAME_WEB_PATTERN, text):
            return await self._parse_game_by_appid(
                match.group("appid"), match.group("game_type")
            )
        if match := re.search(self.GAME_SHARE_PATTERN, text):
            return await self._parse_game_by_appid(
                match.group("share_appid"), match.group("share_game_type")
            )
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

    @staticmethod
    def _canonical_game_web_url(appid: str, game_type: str) -> str:
        normalized_type = game_type.strip().lower() or "pc"
        return f"https://www.xiaoheihe.cn/app/topic/game/{normalized_type}/{appid}"

    async def _parse_game_by_appid(
        self, appid: str, game_type: str
    ) -> ParseResult:
        appid = appid.strip()
        if not appid:
            raise ValueError("无效的小黑盒游戏 appid")
        web_url = self._canonical_game_web_url(appid, game_type)
        async with httpx.AsyncClient(
            timeout=self._timeout(),
            follow_redirects=True,
            headers=self.HEADERS,
        ) as client:
            response = await client.get(
                web_url,
                headers={"Accept": "text/html,application/xhtml+xml,*/*"},
            )
            response.raise_for_status()
            html_text = response.text
            game = self._extract_game_root(html_text, appid)
            steam_appid = self._pick_steam_appid(game, appid)
            intro: dict = {}
            if steam_appid is not None:
                intro_response = await client.get(
                    "https://api.xiaoheihe.cn/game/game_introduction/",
                    params={"steam_appid": steam_appid, "return_json": 1},
                )
                intro_response.raise_for_status()
                intro_payload = intro_response.json()
                if (
                    isinstance(intro_payload, dict)
                    and intro_payload.get("status") == "ok"
                    and isinstance(intro_payload.get("result"), dict)
                ):
                    intro = intro_payload["result"]
            result = self._build_game_result(
                html_text, game, appid, game_type, intro
            )
            return await self.materialize_images(result, client, web_url)

    def _parse_game_state(
        self,
        html_text: str,
        appid: str,
        game_type: str,
        intro: dict,
    ) -> ParseResult:
        game = self._extract_game_root(html_text, appid)
        return self._build_game_result(html_text, game, appid, game_type, intro)

    def _build_game_result(
        self,
        html_text: str,
        game: dict,
        appid: str,
        game_type: str,
        intro: dict,
    ) -> ParseResult:
        image_urls = self._extract_game_images(game, html_text)
        video_urls = self._extract_game_videos(game, html_text)
        extra_lines = [f"游戏平台: {game_type.upper()}"]
        extra_lines.extend(f"附加视频: {url}" for url in video_urls[1:])
        if not image_urls and not video_urls:
            extra_lines.append("未找到可发送的媒体。")
        return ParseResult(
            platform=self.name,
            title=self._build_game_title(game),
            description=self._build_game_desc(html_text, game, intro),
            image_urls=image_urls,
            video_url=video_urls[0] if video_urls else "",
            extra_lines=extra_lines,
        )

    def _extract_game_root(self, html_text: str, appid: str) -> dict:
        payload = self._extract_nuxt_data_payload(html_text)
        if not payload:
            raise ValueError("小黑盒游戏页未找到 __NUXT_DATA__")
        root = self._devalue_resolve_root(payload)
        game = self._find_best_game_dict(root, appid)
        if not game:
            raise ValueError("小黑盒游戏页未找到游戏详情数据")
        return game

    @staticmethod
    def _extract_nuxt_data_payload(html_text: str) -> list | None:
        matched = re.search(
            r'<script[^>]+id=["\']__NUXT_DATA__["\'][^>]*>(.*?)</script>',
            html_text,
            re.DOTALL | re.IGNORECASE,
        )
        if not matched:
            return None
        try:
            payload = json.loads(matched.group(1).strip())
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, list) else None

    @staticmethod
    def _devalue_resolve_root(payload: list):
        total = len(payload)
        memo: dict[int, object] = {}
        resolving: set[int] = set()

        def resolve(value):
            if (
                isinstance(value, int)
                and not isinstance(value, bool)
                and 0 <= value < total
            ):
                return resolve_index(value)
            if isinstance(value, list):
                if (
                    len(value) == 2
                    and isinstance(value[0], str)
                    and value[0]
                    in {
                        "ShallowReactive",
                        "Reactive",
                        "Ref",
                        "ShallowRef",
                        "Readonly",
                        "ShallowReadonly",
                    }
                ):
                    return resolve(value[1])
                return [resolve(item) for item in value]
            if isinstance(value, dict):
                return {key: resolve(item) for key, item in value.items()}
            return value

        def resolve_index(index: int):
            if index in memo:
                return memo[index]
            if index in resolving:
                return None
            resolving.add(index)
            memo[index] = None
            memo[index] = resolve(payload[index])
            resolving.remove(index)
            return memo[index]

        return resolve_index(0) if payload else None

    @staticmethod
    def _find_best_game_dict(root, appid: str) -> dict | None:
        best = None
        best_score = -1
        stack = [root]
        seen: set[int] = set()
        while stack:
            current = stack.pop()
            if isinstance(current, (dict, list)):
                marker = id(current)
                if marker in seen:
                    continue
                seen.add(marker)
            if isinstance(current, dict):
                score = sum(
                    3
                    for key in (
                        "about_the_game",
                        "name",
                        "name_en",
                        "price",
                        "heybox_price",
                        "score",
                        "comment_stats",
                        "screenshots",
                        "share_url",
                        "video_url",
                    )
                    if key in current
                )
                if str(current.get("appid") or "") == appid or str(
                    current.get("steam_appid") or ""
                ) == appid:
                    score += 50
                if appid and appid in str(current.get("share_url") or ""):
                    score += 20
                if score >= 12 and score > best_score:
                    best = current
                    best_score = score
                stack.extend(
                    value
                    for value in current.values()
                    if isinstance(value, (dict, list))
                )
            elif isinstance(current, list):
                stack.extend(
                    value for value in current if isinstance(value, (dict, list))
                )
        return best

    @staticmethod
    def _pick_steam_appid(game: dict, fallback_appid: str) -> int | None:
        try:
            return int(str(game.get("steam_appid") or fallback_appid).strip())
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _build_game_title(game: dict) -> str:
        name = str(game.get("name") or "").strip()
        english_name = str(game.get("name_en") or "").strip()
        if name and english_name:
            return f"{name}（{english_name}）"
        return name or english_name or "小黑盒游戏详情"

    def _build_game_desc(self, html_text: str, game: dict, intro: dict) -> str:
        lines = []
        intro_text = self._format_game_intro_text(
            str(intro.get("about_the_game") or game.get("about_the_game") or "")
        )
        if intro_text:
            lines.append(intro_text)
        if game_types := self._parse_game_types_from_html(html_text):
            lines.append(f"类型：{game_types}")
        score = str(game.get("score") or "").strip()
        stats = game.get("comment_stats")
        score_count = stats.get("score_comment") if isinstance(stats, dict) else None
        if score:
            if isinstance(score_count, int) and score_count > 0:
                lines.append(
                    f"小黑盒评分：{score}（{self._format_people_count(score_count)}）"
                )
            else:
                lines.append(f"小黑盒评分：{score}")
        release_date = str(intro.get("release_date") or "").strip()
        if release_date:
            lines.append(f"发布时间：{release_date.replace('-', '.')}" )
        if developer := self._extract_company_text(intro.get("developers")):
            lines.append(f"开发商：{developer}")
        if publisher := self._extract_company_text(intro.get("publishers")):
            lines.append(f"发行商：{publisher}")
        price = game.get("price")
        if isinstance(price, dict):
            initial = str(price.get("initial") or price.get("current") or "").strip()
            if initial:
                lines.append(f"价格：¥ {initial.replace('¥', '').strip()}")
            lowest = str(price.get("lowest_price") or "").strip()
            if lowest:
                lines.append(f"史低价格：¥ {lowest.replace('¥', '').strip()}")
        heybox_price = game.get("heybox_price")
        if isinstance(heybox_price, dict):
            if yuan := self._format_yuan_from_coin(heybox_price.get("cost_coin")):
                lines.append(f"当前价格：¥ {yuan}")
        return "\n\n".join(lines)

    def _parse_game_types_from_html(self, html_text: str) -> str:
        matched = re.search(
            r'<div class="row-2">.*?<div class="tags">(.*?)</div></div>',
            html_text,
            re.DOTALL | re.IGNORECASE,
        )
        if not matched:
            return ""
        tags_html = matched.group(1)
        common = re.search(
            r'<div class="tag common"[^>]*>(.*?)</div>',
            tags_html,
            re.DOTALL | re.IGNORECASE,
        )
        groups = []
        if common:
            values = [
                self._strip_tags(value)
                for value in re.findall(
                    r"<span[^>]*>(.*?)</span>",
                    common.group(1),
                    re.DOTALL | re.IGNORECASE,
                )
            ]
            values = [value for value in values if value]
            if values:
                groups.append(f"[ {' '.join(values)} ]")
        values = [
            self._strip_tags(value)
            for value in re.findall(
                r'<p class="tag"[^>]*>(.*?)</p>',
                tags_html,
                re.DOTALL | re.IGNORECASE,
            )
        ]
        values = [value for value in values if value]
        if values:
            groups.append(f"[ {' '.join(values)} ]")
        return " ".join(groups)

    @classmethod
    def _format_game_intro_text(cls, text: str) -> str:
        if not text:
            return ""
        value = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
        value = re.sub(r"<[^>]+>", "", value)
        return cls._clean_text(value)

    @classmethod
    def _strip_tags(cls, text: str) -> str:
        return cls._clean_text(re.sub(r"<[^>]+>", "", html.unescape(text)))

    @staticmethod
    def _extract_company_text(items) -> str:
        if not isinstance(items, list):
            return ""
        return ",".join(
            str(item["value"])
            for item in items
            if isinstance(item, dict) and item.get("value")
        )

    @staticmethod
    def _format_people_count(count: int) -> str:
        if count >= 10000:
            return f"{count / 10000:.1f} 万人评价"
        return f"{count} 人评价"

    @staticmethod
    def _format_yuan_from_coin(coin) -> str:
        try:
            value = int(coin) / 1000
        except (TypeError, ValueError):
            return ""
        if value.is_integer():
            return str(int(value))
        return f"{value:.2f}"

    def _extract_game_images(self, game: dict, html_text: str) -> list[str]:
        images = []
        seen = set()

        def add(candidate):
            image_url = self._normalize_image_url(candidate)
            if not image_url:
                return
            image_key = self._image_dedup_key(image_url)
            if image_key in seen:
                return
            lowered = image_url.lower()
            if not any(
                marker in lowered
                for marker in ("gameimg", "steam_item_assets", "screenshot")
            ):
                return
            seen.add(image_key)
            images.append(image_url)

        for key in (
            "screenshots",
            "screenshot_list",
            "screen_shots",
            "images",
            "image_list",
            "game_imgs",
        ):
            values = game.get(key)
            if not isinstance(values, list):
                continue
            for item in values:
                if isinstance(item, dict):
                    for field in ("url", "image", "img", "src"):
                        add(item.get(field))
                else:
                    add(item)
        for field in ("header_img", "cover", "cover_img", "poster", "share_img"):
            add(game.get(field))
        if not images:
            for candidate in re.findall(
                r'https?://[^"\'\s<>]+\.(?:jpg|jpeg|png|webp)(?:\?[^"\'\s<>]*)?',
                html_text,
                re.IGNORECASE,
            ):
                add(candidate)
        return images

    def _extract_game_videos(self, game: dict, html_text: str) -> list[str]:
        videos = []
        seen = set()

        def add(candidate):
            video_url = self._normalize_media_url(candidate)
            if video_url and video_url not in seen:
                seen.add(video_url)
                videos.append(video_url)

        add(game.get("video_url"))
        for candidate in re.findall(
            r'https?://[^"\'\s<>]+\.(?:m3u8|mp4|mov)(?:\?[^"\'\s<>]*)?',
            html_text,
            re.IGNORECASE,
        ):
            add(candidate)
        return videos

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
