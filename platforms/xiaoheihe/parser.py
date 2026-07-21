import re

import httpx

from ...core.contracts import ParseContext, ParseResult
from ...core.parser import BaseParser
from .fingerprint import V4_DATA, V4_EP
from .game import (
    build_game_desc,
    build_game_result,
    canonical_game_web_url,
    extract_game_images,
    extract_game_videos,
    format_yuan_from_coin,
    parse_game_state,
    pick_steam_appid,
)
from .post import (
    clean_text,
    image_dedup_key,
    normalize_image_url,
    normalize_media_url,
    parse_post_contents,
    parse_post_payload,
)
from .signing import RequestSigner


class XiaoheiheParser(BaseParser):
    """负责小黑盒 URL 路由、会话准备与网络请求。"""

    name = "xiaoheihe"
    image_host_suffixes = ("max-c.com", "xiaoheihe.cn")
    CHAR_TABLE = RequestSigner.CHAR_TABLE
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

    def __init__(self, config) -> None:
        super().__init__(config)
        self._signer = RequestSigner()

    async def match(self, context: ParseContext) -> bool:
        return any(
            re.search(pattern, context.combined_text) for pattern in self.PATTERNS
        )

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
        return self.request_timeout

    def _extract_xhh_tokenid_from_cookies(self) -> str | None:
        cookie_header = str(self.config.get("xiaoheihe_cookies", ""))
        matched = re.search(r"(?:^|;\s*)x_xhh_tokenid=([^;]+)", cookie_header)
        return matched.group(1) if matched else None

    async def _build_request_context(self) -> dict[str, str]:
        token = self._extract_xhh_tokenid_from_cookies()
        if not token:
            device_id = await self._fetch_device_id()
            if not device_id:
                raise ValueError("小黑盒 deviceprofile 未返回 deviceId")
            return {"x_xhh_tokenid": f"B{device_id}", "device_id": device_id}
        return {
            "x_xhh_tokenid": token,
            "device_id": token[1:] if token.startswith("B") else "",
        }

    async def _fetch_device_id(self) -> str:
        payload = {
            "appId": "heybox_website",
            "organization": "0yD85BjYvGFAvHaSQ1mc",
            "ep": V4_EP,
            "data": V4_DATA,
            "os": "web",
            "encode": 5,
            "compress": 2,
        }
        async with httpx.AsyncClient(
            timeout=self._timeout(),
            follow_redirects=False,
            headers={"Accept": "application/json, text/plain, */*"},
        ) as client:
            response = await client.post(
                "https://fp-it.portal101.cn/deviceprofile/v4", json=payload
            )
            response.raise_for_status()
            body = response.json()
        detail = body.get("detail") if isinstance(body, dict) else None
        device_id = detail.get("deviceId") if isinstance(detail, dict) else None
        if not device_id:
            raise ValueError("小黑盒 deviceprofile 未返回 deviceId")
        return str(device_id)

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
                headers={"Cookie": f"x_xhh_tokenid={request_context['x_xhh_tokenid']}"},
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or payload.get("status") != "ok":
                raise ValueError("小黑盒 link/tree 请求失败")
            result_root = payload.get("result")
            if not isinstance(result_root, dict):
                raise ValueError("小黑盒 link/tree 结果为空")
            result = parse_post_payload(result_root)
            return await self.materialize_images(result, client, referer)

    async def _parse_game_by_appid(self, appid: str, game_type: str) -> ParseResult:
        appid = appid.strip()
        if not appid:
            raise ValueError("无效的小黑盒游戏 appid")
        request_context = await self._build_request_context()
        web_url = canonical_game_web_url(appid, game_type)
        async with httpx.AsyncClient(
            timeout=self._timeout(),
            follow_redirects=False,
            headers=self.HEADERS,
        ) as client:
            detail_response = await client.get(
                "https://api.xiaoheihe.cn/game/get_game_detail/",
                params={
                    "app": "heybox",
                    "os_type": "web",
                    "x_app": "heybox_website",
                    "x_client_type": "web",
                    "x_os_type": "Windows",
                    "x_client_version": "",
                    "client_type": "web",
                    "web_version": "3.0",
                    "version": "999.0.4",
                    "steam_appid": appid,
                    **self._sign_path("/game/get_game_detail/"),
                },
                headers={"Cookie": f"x_xhh_tokenid={request_context['x_xhh_tokenid']}"},
            )
            detail_response.raise_for_status()
            detail_payload = detail_response.json()
            if (
                not isinstance(detail_payload, dict)
                or detail_payload.get("status") != "ok"
                or not isinstance(detail_payload.get("result"), dict)
            ):
                raise ValueError("小黑盒 get_game_detail 请求失败")
            game = detail_payload["result"]
            steam_appid = pick_steam_appid(game, appid)
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
            result = build_game_result("", game, appid, game_type, intro)
            return await self.materialize_images(result, client, web_url)

    def _sign_path(self, path: str) -> dict[str, str | int]:
        return self._signer.sign_path(path)

    def _ov(self, path: str, timestamp: int, nonce: str) -> str:
        return self._signer.ov(path, timestamp, nonce)

    @classmethod
    def _parse_post_payload(cls, payload: object) -> ParseResult:
        return parse_post_payload(payload)

    @classmethod
    def _parse_post_contents(cls, raw_text: object):
        return parse_post_contents(raw_text)

    @staticmethod
    def _clean_text(text: str) -> str:
        return clean_text(text)

    @staticmethod
    def _normalize_media_url(value: object) -> str:
        return normalize_media_url(value)

    @classmethod
    def _normalize_image_url(cls, value: object) -> str:
        return normalize_image_url(value)

    @staticmethod
    def _image_dedup_key(url: str) -> str:
        return image_dedup_key(url)

    @staticmethod
    def _canonical_game_web_url(appid: str, game_type: str) -> str:
        return canonical_game_web_url(appid, game_type)

    def _parse_game_state(
        self, html_text: str, appid: str, game_type: str, intro: dict
    ) -> ParseResult:
        return parse_game_state(html_text, appid, game_type, intro)

    def _build_game_desc(self, html_text: str, game: dict, intro: dict) -> str:
        return build_game_desc(html_text, game, intro)

    def _extract_game_images(self, game: dict, html_text: str) -> list[str]:
        return extract_game_images(game, html_text)

    def _extract_game_videos(self, game: dict, html_text: str) -> list[str]:
        return extract_game_videos(game, html_text)

    @staticmethod
    def _format_yuan_from_coin(coin) -> str:
        return format_yuan_from_coin(coin)
