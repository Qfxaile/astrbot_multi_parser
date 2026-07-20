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


V4_EP = (
    "V1ZCERzVgMWrKv+VcTl5QmS9JuPWLOQ8A0mACeTyYXtTbiguOrHhwaqnagZ6zdAgF"
    "4WpAYBvUH3EDnPRlNWut4CTDU1tCa80BSnvTMC9X1j9Kh6IMlGmzPIqpBzzx9r7Nt"
    "9XtUhv2WiQ2BgPnUwOFe7gN9r8Yj3184qxn1btJL8="
)
V4_DATA = (
    "abbbe96a1579aa6fe4fa84e875851b7d7a843a14c5c9573c771d9c1443c9b3a"
    "d7603a8d9d67dbc9bd001bf42702ac82e4a6979323ff305eecd74b9620ee140"
    "0c135f840b35d9402ec3e3a93fcb3d0d3d6b3e740f5176b72225b6fb8a0d483"
    "cab753aa71062dc9b59bc8de950628f23607301c6cd94e75f680b86485a11ac"
    "36eba1413e9f14b274eadff30114dfb1cedadc4bd08ef83c5b2d048970d07d3"
    "943afef809b44e3b9fee602c91e274fee1523a8beee7e7cec85680b279d616d"
    "da15e98b1b0aa718276bcdb05d4ac3e44e72da220e0ea798ad7452aec01d0db"
    "c31ad6bf147eab7f7e539d35fe5149110aae5c7069a67eba4aae638505819f8"
    "9e2a58bc3b5001c8a5045334121ef04a8e442d7dbb7776bd6013674d2c0028a"
    "f131bf6bde47b90dce5c8b9463c9f83d0e7264145c2f6f259d70c4d63a4996b"
    "b7c0074e8a59fa298ad144ec139cb29bc94074fbe2f4a88400d85c003793e2b"
    "e2077184c3ba2e792926fce25f24d3a764a7c2667446173c74aa704d0d517f2"
    "10926aaef05376230b43c3a676dad6ff1c9603553d66eadfb492445eac44745"
    "acc620b325560d4941c10e05f3099a17a553fd763a1b7d6ef29f512e436bdfa"
    "9fa7c5a70b6a5f91bbcb21946fc2ce92db0c92930008b0fc82e90c3c73f9265"
    "2ca388f77b262a918cf59160fa88e481138ee7fe9a9b51d7949a74d22d1dab4"
    "e865c12325bfb5b9e748526afb6d8a05c543fd6dc72e81b06a4ebbf8149fca5"
    "37a19330da2011eec0229e2302babe239397aa1c2292ab3807cf0aa129d078a"
    "a9da010003eac5bb2c06435fbbe9bee7543290c1224745bb485d78f42ee4e82"
    "afb27a38befc60a688fb2514795064926bf205357bd46b7c14dd15aea2cab48"
    "5c993f0df5a20811d0a7b3bfb1fcb0737c8305675e9bdac396ef8cffb0b6bc4"
    "700c3d881c1945329b721b9080bed46b18105b7c9fea4f8276f0fcd09fe99ec"
    "52fa50b11e12a19eb9d091ecde701ab2879e2d7727386b28bbde8d62832e1ad"
    "822ea57b383cdd3767e8ee64e201bf00fe9cc8428ece3262550764fea47c69e"
    "e4339de98767f034d8852993fdefa315d9dcda71a74b665804706d4f9a8c139"
    "3670c2220e4ceac833620e0dc8175eb7a77b8b37c1a9d9940c67d44c8bc6b5f"
    "9e46273e2f5149d3d3148e8f7a02c4a4c3c998924b7d0e93528952034adc20d"
    "c342404a8606f0c07cb2b98c4a5434e69b69282daf952f586b9eed4b4f1ef0c"
    "fe5c6d156d14fb5057c8c32a355d07e2f56737d1ccfad573d42c840bbe8b750"
    "388211f2c0c5d6a1e34e7741389a742dff58bb0b9f339707a349a09519ca78d"
    "5e4f1baaf2598ab9001c15824494eecc17735e69a193e5437cbe44c6f156a0b"
    "b8df4fed5edefd4f56f4ef0b4d8cc40fe623836da3c5e662005825c9d344074"
    "be2306d6241c163fe92a6ce40ff60538d7464f5a06b6bb9ca1e6f18491ca3c7"
    "d6c00e299cbb1ca1c525a981fc6c6f2bb05f709101099b8bd0d2c2a628d94c6"
    "1aa97fdd58c9f357359fbd5be9e8f0f534f4481fb780d58e3e599e01fdd5a7f"
    "c5fb7e01b76fd58b2f264947d2149fefa57577ef326e264fc827939329031d9"
    "01be7579ecf5fccdab11c615c1a053f198297c0723faf8b17ea3335d49df2bf"
    "dd17271c2b64745b1f412d87297edd4404a4ae5312debf73b66afcc3d884b93"
    "8de41b6ee87265ce624897f3557ebe2d97e6fb17f1dc6a893e48dfa16ef2bff"
    "d8f3e06f0a1fcf44c7f2efa372e0ff61344c93f4a2a66538fcc134cd0bf94d5"
    "4c969cda4392af70608cbab6cfa340b674ba3a59385c0ed9bb236ff6ed10e1e"
    "5a9d4b6529c075dc1ac23cfdae18ab1651a5ee747322e51e3cc6035ca929789"
    "00924e661a2694a47873569baa95fd821711dc53a1e0299ed707e337b570591"
    "a3f61a5e39f8a75771da1613e8236c9b1b94cb5617fdaf2424d68a7fbd83ebf"
    "356fc87e8a805bee5bbd20a55a70881394d7624b1dcf5a135f1cf40b842eca3"
    "3d46b72447e0a2e85adf6c26efa6cc73b63573840f7b6229fb03ab45a8b639b"
    "5a66bbd6f63d10e59db49d7a9c9af3e3aeb79b7b756e24d5002917e7e788018"
    "4f80fcc605a1ba825c779e6083fd7fb0920bbcee021ec8e35427391b871b149"
    "c306c2dbda602044cd53ec424dd70cfd1c14a23c9964c039258cff4b75112f8"
    "15d9717433c1989ec398cd2acd67c89be82a409e0ef8f3e9ea8ec8b51b5ea5a"
    "005b5e735978d9a2987a76d62a2af230e30dc6327f7c0d153add27c7e8a320e"
    "4df6c05ab91fe0b9f6f9e13c50f39454066776503eb2ec84b74b4b2d5228627"
    "d81c938f7201610c9b703e4fd283a94835b7387db2880443a050d3eb0859aa1"
    "efd0f9bb7613b6b918ec2f7b5bb3e7722105b595e7973a93e3de8153a0f8e5b"
    "fd1aa6cefc6285fea85e8381ddcce98b31dda33db2a3c80ac04df14b872c805"
    "15373f231c3653fb2db799b32e83e59fb0f5763febca3d291b49bf83dd7ebd6"
    "1229300b65d44964d9e679f6061a0b2ea1bcd9f5af9bf710047237d87d13394"
    "ea8b4627c6997589d0b58379d025b076460eab88d6615ee92b0aa6c47f721f9"
    "7e0b5bbe721f06544d0a1bb81402697f2d72ad32c791dab45064b4d18460602"
    "9494b268feaebb268e7f92352dc3482f857c14885aabbad98a43e5f8fa5d77d"
    "61dc22f23080b9e6403c76f5fb862d7520ab85ae7c1d0e339729f664e7d668f"
    "4b9d1301acabb62fda5940db236ea9d2ca896cbb6a13eda6120fa5881453cb4"
    "490438460c00db4cd4bdf5df993d3a8d5726c756015eed542e0a4b910570f39"
    "7211c3f84f6a0d038e82270f94543e8da1e8d0cffd8f4f561daaf6003ad1fad"
    "fdd89c50f057a79225d8647aead74b33216e328c4204686b4ae93ce5f7ee25e"
    "1c83fe2cb72c67589aa4865d278ff7a112d09c16707de8acd61b49b901a3266"
    "e8ef55f1351fdc3013154635e51e649cbf31fc9b32f6956800834ca73e0b75b"
    "2b54d7125257eb6c24ebff52b741109be6da99bb6e0ffab85c3c219550ec3fc"
    "b12e2e4d0234627b061193c290baa1be73241be70925c08d33e6efdd44eca9a"
    "5160bdc5b47bd1f9d3f2cbf38848cf1aaa2a4827f86e43e06246b3bf94cb0b9"
    "f050c89533a3be9ffecefebd1a92e04197f18d7fadc0bfc8664de18425d5c03"
    "59b58049267934756f513bd68ea427b38f15213f42cce05cd59f5ea502967ec"
    "6a096daaa5e5d2a373227f2fe4514e27dfa012d708f7e94a286452972b5fab4"
    "581ecee3df40bad802cbb50b1a5d9dd3323a5f7c61ab893b16782a0ba64fd42"
    "10c30ac00f9d21b9124e5e5b323f43badf56761e1eea5c86ff61f19ce1485f4"
    "2cf6cadd751bbfb2ef87229eee5068ef6e209f123d29a571a374974ceac2e77"
    "f143faba60fc5d16f88d801fa01d879420b5d1393ad5b2bc913e3b0ba7155a6"
    "7648196573126273cccc79f2eac32ab68d72cc0f7170feca9c9726af9d65962"
    "663d5281372386ec88bd2fa82316f687535ecd39f00658523708ca4785529f5"
    "93baf100597ed00c15ae8ff87baa295871680b4096ac03a550f0f015297198b"
    "1a93f38cfefbeceabc099c1026664d77f616b4f069cf8bf53d2684b9a4d933c"
    "3c65a3aef21559527bfc6586e0247efa244a0a355b43751bc09be8012699468"
    "a8c332d60b11bb4881bf56b92ead10e059ac40f83a4d6725cacbc1bb307c839"
    "c4edc8b5484b9e2935842e867e739223f2eaaaff04d9701cfa49e3f80be4f2d"
    "1b7e8eb76fd7f33dfa79831f75ee65a75b7c7fff98254818f1ab77bca856656"
    "4d48e0012733dd426bf841f27f960394b1bacb8a3e36b96c41d751584cd580f"
    "ef1b6a8bf990487268348f682a27549ecbb9674b14f2fc97f203f3468f248ec"
    "3cf5171aa5e8a8d31a9a433c4f7644736aaf6695b28771fe66b4736e3afb322"
    "11ad534b05641600d2cdc79a251fc4c4e5540df9a40aaad329fedd49a429b20"
    "70e1345a4146c297ee2a03f056675054e83207d17de21242032c30398259440"
    "84e60cbd70eb4c469859824cd7d04340de0d19e614a0826a63c63e15c3372b1"
    "7515d4b6951ff6c612f65c3e6538fd0515bcb4814bb641fca5a45c7dae9"
)


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
            device_id = await self._fetch_device_id()
            if not device_id:
                raise ValueError("小黑盒 deviceprofile 未返回 deviceId")
            return {
                "x_xhh_tokenid": f"B{device_id}",
                "device_id": device_id,
            }
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
                "https://fp-it.portal101.cn/deviceprofile/v4",
                json=payload,
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
