"""实现微信扫码授权与腾讯元宝 Cookie 提取。"""

import re
import secrets
import string
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urlencode, urljoin, urlsplit

import httpx

from ...core.authentication import (
    LoginPollResult,
    LoginPollState,
    PlatformLoginError,
    PlatformLoginProvider,
    QRLoginChallenge,
)
from ...core.http import request_timeout


@dataclass
class _WeChatQRSession:
    """保存一次微信开放平台授权所需的内存态。"""

    uuid: str
    nonce: str
    last_status: int | None = None


class _QRImageParser(HTMLParser):
    """从微信开放平台授权页提取二维码图片候选地址。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.image_urls: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag != "img":
            return
        attributes = dict(attrs)
        class_names = str(attributes.get("class") or "").split()
        if not any("qrcode" in name for name in class_names):
            return
        image_url = str(attributes.get("src") or "").strip()
        if image_url:
            self.image_urls.append(image_url)


class WeChatLoginProvider(PlatformLoginProvider):
    """通过微信开放平台扫码建立腾讯元宝解析登录态。"""

    display_name = "微信"
    cookie_config_key = "wechat_yuanbao_cookies"
    OAUTH_APP_ID = "wx12b75947931a04ec"
    OAUTH_URL = "https://open.weixin.qq.com/connect/qrconnect"
    QR_IMAGE_HOST = "open.weixin.qq.com"
    QR_POLL_URL = "https://long.open.weixin.qq.com/connect/l/qrconnect"
    CALLBACK_URL = "https://yuanbao.tencent.com/scan"
    YUANBAO_HOST = "yuanbao.tencent.com"
    QR_EXPIRES_IN_SECONDS = 300
    MAX_AUTH_PAGE_BYTES = 512 * 1024
    MAX_QR_IMAGE_BYTES = 512 * 1024
    MAX_POLL_RESPONSE_BYTES = 16 * 1024
    MAX_CALLBACK_RESPONSE_BYTES = 512 * 1024
    MAX_LOGIN_REDIRECTS = 5
    COOKIE_NAMES = ("hy_user", "hy_token")
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )
    _UUID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,128}")
    _POLL_PATTERN = re.compile(
        rb"window\.wx_errcode\s*=\s*(\d+)\s*;\s*"
        rb"window\.wx_code\s*=\s*['\"]([^'\"]*)['\"]"
    )
    _AUTH_CODE_PATTERN = re.compile(rb"[A-Za-z0-9_-]{1,512}")
    _REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})
    _RISK_MARKERS = (
        "captcha",
        "安全验证",
        "人机验证",
        "滑块验证",
        "设备验证",
        "访问异常",
        "操作频繁",
    )

    def __init__(
        self,
        config,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=request_timeout(config),
            follow_redirects=False,
            headers={
                "Accept-Language": "zh-CN,zh;q=0.9",
                "User-Agent": self.USER_AGENT,
            },
        )
        self._sessions: dict[str, _WeChatQRSession] = {}

    async def create_qr_challenge(self) -> QRLoginChallenge:
        """创建微信开放平台二维码并下载受信任的二维码图片。"""
        nonce = self._new_nonce()
        redirect_uri = f"{self.CALLBACK_URL}?{urlencode({'nonce': nonce})}"
        try:
            content, content_type, status_code, _ = await self._read_limited_response(
                self.OAUTH_URL,
                limit=self.MAX_AUTH_PAGE_BYTES,
                params={
                    "appid": self.OAUTH_APP_ID,
                    "scope": "snsapi_login",
                    "redirect_uri": redirect_uri,
                    "state": "wechat_login",
                    "login_type": "jssdk",
                    "self_redirect": "false",
                    "style": "white",
                },
            )
        except PlatformLoginError:
            raise
        except httpx.HTTPError as exc:
            raise PlatformLoginError(
                "微信登录服务请求失败，请稍后重试。"
            ) from exc

        if status_code in self._REDIRECT_STATUS_CODES:
            raise PlatformLoginError("微信登录服务返回了不安全的重定向。")
        if status_code >= 400:
            raise PlatformLoginError("微信暂时无法创建登录二维码，请稍后重试。")
        if "text/html" not in content_type and not content.lstrip().startswith(b"<"):
            raise PlatformLoginError("微信登录服务返回了无效响应。")

        qr_url, uuid = self._extract_qr_image(content)
        if not qr_url or not uuid:
            if self._contains_risk_marker(content):
                raise self._verification_error()
            raise PlatformLoginError("微信返回了无效的二维码登录信息。")

        image_bytes = await self._download_qr_image(qr_url)
        session_key = secrets.token_urlsafe(32)
        self._sessions[session_key] = _WeChatQRSession(uuid=uuid, nonce=nonce)
        return QRLoginChallenge(
            session_key=session_key,
            image_bytes=image_bytes,
            expires_in_seconds=self.QR_EXPIRES_IN_SECONDS,
        )

    async def poll_qr_status(self, session_key: str) -> LoginPollResult:
        """轮询扫码状态，成功后完成元宝回调并提取最小 Cookie。"""
        session = self._sessions.get(session_key)
        if session is None:
            raise PlatformLoginError("微信登录会话无效，请重新发起登录。")

        params = {"uuid": session.uuid}
        if session.last_status is not None:
            params["last"] = str(session.last_status)
        try:
            content, _, status_code, _ = await self._read_limited_response(
                self.QR_POLL_URL,
                limit=self.MAX_POLL_RESPONSE_BYTES,
                params=params,
            )
        except PlatformLoginError:
            raise
        except httpx.HTTPError as exc:
            raise PlatformLoginError(
                "微信登录状态查询失败，请稍后重试。"
            ) from exc

        if status_code in self._REDIRECT_STATUS_CODES or status_code >= 400:
            raise PlatformLoginError("微信登录状态查询失败，请稍后重试。")
        match = self._POLL_PATTERN.search(content)
        if match is None:
            if self._contains_risk_marker(content):
                raise self._verification_error()
            raise PlatformLoginError(
                "微信返回了无法识别的登录状态，请重新发起登录。"
            )

        poll_status = int(match.group(1))
        auth_code = match.group(2)
        if poll_status == 408:
            session.last_status = None
            return LoginPollResult(LoginPollState.WAITING)
        if poll_status == 404:
            session.last_status = poll_status
            return LoginPollResult(LoginPollState.SCANNED)
        if poll_status == 402:
            self._sessions.pop(session_key, None)
            return LoginPollResult(LoginPollState.EXPIRED)
        if poll_status == 403:
            self._sessions.pop(session_key, None)
            raise PlatformLoginError(
                "微信登录已在手机端取消，请重新发起登录。"
            )
        if poll_status == 405:
            if self._AUTH_CODE_PATTERN.fullmatch(auth_code) is None:
                raise PlatformLoginError("微信返回了无效的登录确认信息。")
            await self._complete_yuanbao_login(
                nonce=session.nonce,
                auth_code=auth_code.decode("ascii"),
            )
            self._sessions.pop(session_key, None)
            cookie_header = self._cookie_header()
            if not all(f"{name}=" in cookie_header for name in self.COOKIE_NAMES):
                raise PlatformLoginError(
                    "微信登录成功，但响应中缺少有效的腾讯元宝登录凭据。"
                )
            return LoginPollResult(LoginPollState.SUCCESS, cookie_header)

        raise PlatformLoginError(
            "微信返回了无法识别的登录状态，请重新发起登录。"
        )

    async def close(self) -> None:
        """清理二维码会话并关闭由适配器创建的 HTTP 客户端。"""
        self._sessions.clear()
        if self._owns_client:
            await self._client.aclose()

    async def _download_qr_image(self, url: str) -> bytes:
        try:
            content, content_type, status_code, _ = await self._read_limited_response(
                url,
                limit=self.MAX_QR_IMAGE_BYTES,
            )
        except PlatformLoginError:
            raise
        except httpx.HTTPError as exc:
            raise PlatformLoginError(
                "微信登录二维码获取失败，请稍后重试。"
            ) from exc
        if status_code in self._REDIRECT_STATUS_CODES:
            raise PlatformLoginError("微信登录二维码返回了不安全的重定向。")
        if status_code >= 400:
            raise PlatformLoginError("微信登录二维码获取失败，请稍后重试。")

        media_type = content_type.split(";", 1)[0].strip()
        supported_type = media_type in {"image/jpeg", "image/png"}
        supported_signature = content.startswith(b"\x89PNG\r\n\x1a\n") or content.startswith(
            b"\xff\xd8\xff"
        )
        if not supported_type or not supported_signature:
            raise PlatformLoginError("微信返回了无效的登录二维码图片。")
        return content

    async def _complete_yuanbao_login(
        self,
        *,
        nonce: str,
        auth_code: str,
    ) -> None:
        # 微信授权码只发送到元宝回调；后续 Location 每一跳都重新校验，
        # 防止平台异常响应把一次性凭据或已写入的 Cookie 带到外域。
        current_url = self.CALLBACK_URL
        request_params: dict[str, str] | None = {
            "nonce": nonce,
            "code": auth_code,
            "state": "wechat_login",
        }
        for _ in range(self.MAX_LOGIN_REDIRECTS + 1):
            if not self._is_trusted_yuanbao_url(current_url):
                raise PlatformLoginError("微信返回了无效的登录确认信息。")
            try:
                content, _, status_code, location = (
                    await self._read_limited_response(
                        current_url,
                        limit=self.MAX_CALLBACK_RESPONSE_BYTES,
                        params=request_params,
                    )
                )
            except PlatformLoginError:
                raise
            except httpx.HTTPError as exc:
                raise PlatformLoginError(
                    "微信登录确认请求失败，请稍后重试。"
                ) from exc
            request_params = None

            if status_code in {403, 429} or self._contains_risk_marker(content):
                raise self._verification_error()
            if status_code not in self._REDIRECT_STATUS_CODES:
                if status_code >= 400:
                    raise PlatformLoginError(
                        "微信登录确认请求失败，请稍后重试。"
                    )
                return
            if not location or len(location) > 2048:
                raise PlatformLoginError("微信返回了无效的登录确认信息。")
            current_url = urljoin(current_url, location)
        raise PlatformLoginError("微信登录确认重定向次数超过安全限制。")

    async def _read_limited_response(
        self,
        url: str,
        *,
        limit: int,
        **kwargs,
    ) -> tuple[bytes, str, int, str]:
        async with self._client.stream(
            "GET",
            url,
            follow_redirects=False,
            **kwargs,
        ) as response:
            content = bytearray()
            async for chunk in response.aiter_bytes():
                if len(content) + len(chunk) > limit:
                    raise PlatformLoginError("微信登录服务响应超过安全限制。")
                content.extend(chunk)
            return (
                bytes(content),
                response.headers.get("Content-Type", "").lower(),
                response.status_code,
                response.headers.get("Location", ""),
            )

    @classmethod
    def _extract_qr_image(cls, content: bytes) -> tuple[str, str]:
        parser = _QRImageParser()
        try:
            parser.feed(content.decode("utf-8", errors="replace"))
            parser.close()
        except ValueError:
            return "", ""
        for image_url in parser.image_urls:
            try:
                parsed = urlsplit(image_url)
                port = parsed.port
            except ValueError:
                continue
            path_match = re.fullmatch(r"/connect/qrcode/([^/]+)", parsed.path)
            if (
                parsed.scheme != "https"
                or parsed.hostname != cls.QR_IMAGE_HOST
                or parsed.username is not None
                or parsed.password is not None
                or port not in {None, 443}
                or path_match is None
            ):
                continue
            uuid = path_match.group(1)
            if cls._UUID_PATTERN.fullmatch(uuid) is not None:
                return image_url, uuid
        return "", ""

    def _cookie_header(self) -> str:
        cookies: dict[str, str] = {}
        for cookie in self._client.cookies.jar:
            domain = str(cookie.domain or "").lstrip(".").lower()
            if domain != self.YUANBAO_HOST:
                continue
            if cookie.name in self.COOKIE_NAMES and cookie.value:
                cookies[cookie.name] = cookie.value
        return "; ".join(
            f"{name}={cookies[name]}" for name in self.COOKIE_NAMES if name in cookies
        )

    @classmethod
    def _contains_risk_marker(cls, content: bytes) -> bool:
        text = content.decode("utf-8", errors="ignore").lower()
        return any(marker in text for marker in cls._RISK_MARKERS)

    @staticmethod
    def _verification_error() -> PlatformLoginError:
        return PlatformLoginError(
            "微信登录触发了平台人机、设备验证或风控，"
            "当前私聊流程无法继续，请稍后重试或手工配置 Cookies。"
        )

    @classmethod
    def _is_trusted_yuanbao_url(cls, url: str) -> bool:
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError:
            return False
        return (
            parsed.scheme == "https"
            and parsed.hostname == cls.YUANBAO_HOST
            and parsed.username is None
            and parsed.password is None
            and port in {None, 443}
        )

    @staticmethod
    def _new_nonce() -> str:
        alphabet = string.ascii_letters + string.digits
        return "".join(secrets.choice(alphabet) for _ in range(16))
