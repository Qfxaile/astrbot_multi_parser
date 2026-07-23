"""实现抖音二维码登录与 Cookie 提取。"""

import json
import re
from urllib.parse import urljoin, urlsplit

import httpx

from ...core.authentication import (
    LoginPollResult,
    LoginPollState,
    PlatformLoginError,
    PlatformLoginProvider,
    QRLoginChallenge,
)
from ...core.http import request_timeout


class DouyinLoginProvider(PlatformLoginProvider):
    """通过抖音官方网页二维码接口建立管理员登录态。"""

    display_name = "抖音"
    cookie_config_key = "douyin_cookies"
    QR_GENERATE_URL = "https://sso.douyin.com/get_qrcode/"
    QR_POLL_URL = "https://sso.douyin.com/check_qrconnect/"
    LOGIN_SERVICE_URL = "https://www.douyin.com/"
    QR_EXPIRES_IN_SECONDS = 180
    MAX_RESPONSE_BYTES = 64 * 1024
    MAX_QR_IMAGE_BYTES = 512 * 1024
    MAX_LOGIN_REDIRECTS = 5
    COOKIE_NAMES = (
        "sessionid",
        "sessionid_ss",
        "sid_guard",
        "sid_tt",
        "uid_tt",
        "uid_tt_ss",
        "ttwid",
    )
    LOGIN_HOST_SUFFIXES = ("douyin.com", "iesdouyin.com")
    QR_IMAGE_HOST_SUFFIXES = (
        "douyinpic.com",
        "byteimg.com",
        "douyincdn.com",
        "pstatp.com",
        "bytedance.com",
    )
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    COMMON_PARAMS = {
        "aid": "6383",
        "account_sdk_source": "sso",
        "sdk_version": "2.2.5_beta.1",
        "language": "zh",
    }
    _SESSION_KEY_PATTERN = re.compile(r"[A-Za-z0-9._~=-]{1,512}")
    _REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})

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
                "User-Agent": self.USER_AGENT,
                "Referer": self.LOGIN_SERVICE_URL,
            },
        )

    async def create_qr_challenge(self) -> QRLoginChallenge:
        """创建二维码会话并下载受信任的官方二维码图片。"""
        payload = await self._get_payload(
            self.QR_GENERATE_URL,
            params={
                **self.COMMON_PARAMS,
                "service": self.LOGIN_SERVICE_URL,
                "need_logo": "true",
                "need_short_url": "true",
            },
        )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise PlatformLoginError("抖音暂时无法创建登录二维码，请稍后重试。")

        qr_url = str(data.get("qrcode") or "")
        session_key = str(data.get("token") or "")
        if (
            len(qr_url) > 2048
            or not self._is_trusted_https_url(qr_url, self.QR_IMAGE_HOST_SUFFIXES)
            or self._SESSION_KEY_PATTERN.fullmatch(session_key) is None
        ):
            raise PlatformLoginError("抖音返回了无效的二维码登录信息。")

        return QRLoginChallenge(
            session_key=session_key,
            image_bytes=await self._download_qr_image(qr_url),
            expires_in_seconds=self.QR_EXPIRES_IN_SECONDS,
        )

    async def poll_qr_status(self, session_key: str) -> LoginPollResult:
        """轮询扫码状态，成功后完成受控跳转并提取必要 Cookie。"""
        if self._SESSION_KEY_PATTERN.fullmatch(session_key) is None:
            raise PlatformLoginError("抖音登录会话无效，请重新发起登录。")

        payload = await self._get_payload(
            self.QR_POLL_URL,
            params={
                **self.COMMON_PARAMS,
                "service": self.LOGIN_SERVICE_URL,
                "token": session_key,
                "need_logo": "true",
                "need_short_url": "true",
            },
        )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise PlatformLoginError("抖音登录状态查询失败，请稍后重试。")

        status = str(data.get("status") or "").lower()
        if status in {"1", "new"}:
            return LoginPollResult(LoginPollState.WAITING)
        if status in {"2", "scanned"}:
            return LoginPollResult(LoginPollState.SCANNED)
        if status in {"4", "5", "expired"}:
            # 状态 4 会轮换二维码和令牌；私聊中不能替换已发送图片，要求重新发起。
            return LoginPollResult(LoginPollState.EXPIRED)
        if status == "3":
            redirect_url = str(data.get("redirect_url") or "")
            if not self._is_trusted_https_url(
                redirect_url, self.LOGIN_HOST_SUFFIXES
            ):
                raise PlatformLoginError("抖音返回了无效的登录确认信息。")
            await self._complete_login_redirects(redirect_url)
            cookie_header = self._cookie_header()
            if not any(
                f"{name}=" in cookie_header
                for name in ("sessionid", "sessionid_ss")
            ):
                raise PlatformLoginError(
                    "抖音登录成功，但响应中缺少有效登录凭据。"
                )
            return LoginPollResult(LoginPollState.SUCCESS, cookie_header)
        raise PlatformLoginError("抖音返回了无法识别的登录状态，请重新发起登录。")

    async def close(self) -> None:
        """关闭由适配器创建的 HTTP 客户端。"""
        if self._owns_client:
            await self._client.aclose()

    async def _get_payload(self, url: str, **kwargs) -> dict:
        try:
            content, content_type = await self._read_limited_response(
                url,
                limit=self.MAX_RESPONSE_BYTES,
                **kwargs,
            )
            stripped = content.lstrip()
            if "text/html" in content_type or stripped.startswith(b"<"):
                raise self._verification_error()
            payload = json.loads(content)
        except PlatformLoginError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise PlatformLoginError("抖音登录服务请求失败，请稍后重试。") from exc
        if not isinstance(payload, dict):
            raise PlatformLoginError("抖音登录服务返回了无效响应。")
        if self._requires_verification(payload):
            raise self._verification_error()
        return payload

    async def _download_qr_image(self, url: str) -> bytes:
        try:
            content, content_type = await self._read_limited_response(
                url,
                limit=self.MAX_QR_IMAGE_BYTES,
            )
        except PlatformLoginError:
            raise
        except httpx.HTTPError as exc:
            raise PlatformLoginError("抖音登录二维码获取失败，请稍后重试。") from exc

        supported_type = content_type.split(";", 1)[0].strip() in {
            "image/jpeg",
            "image/png",
            "image/webp",
        }
        supported_signature = (
            content.startswith(b"\x89PNG\r\n\x1a\n")
            or content.startswith(b"\xff\xd8\xff")
            or (content.startswith(b"RIFF") and content[8:12] == b"WEBP")
        )
        if not supported_type or not supported_signature:
            raise PlatformLoginError("抖音返回了无效的登录二维码图片。")
        return content

    async def _read_limited_response(
        self,
        url: str,
        *,
        limit: int,
        **kwargs,
    ) -> tuple[bytes, str]:
        async with self._client.stream(
            "GET",
            url,
            follow_redirects=False,
            **kwargs,
        ) as response:
            if response.is_redirect:
                raise PlatformLoginError("抖音登录服务返回了不安全的重定向。")
            response.raise_for_status()
            content = bytearray()
            async for chunk in response.aiter_bytes():
                if len(content) + len(chunk) > limit:
                    raise PlatformLoginError("抖音登录服务响应超过安全限制。")
                content.extend(chunk)
            return bytes(content), response.headers.get("Content-Type", "").lower()

    async def _complete_login_redirects(self, redirect_url: str) -> None:
        current_url = redirect_url
        for _ in range(self.MAX_LOGIN_REDIRECTS + 1):
            if not self._is_trusted_https_url(
                current_url, self.LOGIN_HOST_SUFFIXES
            ):
                raise PlatformLoginError("抖音返回了无效的登录确认信息。")
            try:
                async with self._client.stream("GET", current_url) as response:
                    if response.status_code not in self._REDIRECT_STATUS_CODES:
                        response.raise_for_status()
                        return
                    location = response.headers.get("Location", "")
            except httpx.HTTPError as exc:
                raise PlatformLoginError(
                    "抖音登录确认请求失败，请稍后重试。"
                ) from exc
            if not location:
                raise PlatformLoginError("抖音返回了无效的登录确认信息。")
            if len(location) > 2048:
                raise PlatformLoginError("抖音返回了无效的登录确认信息。")
            current_url = urljoin(current_url, location)
        raise PlatformLoginError("抖音登录确认重定向次数超过安全限制。")

    def _cookie_header(self) -> str:
        cookies: dict[str, str] = {}
        for cookie in self._client.cookies.jar:
            domain = str(cookie.domain or "").lstrip(".").lower()
            if not self._is_trusted_cookie_domain(domain):
                continue
            if cookie.name in self.COOKIE_NAMES and cookie.value:
                cookies[cookie.name] = cookie.value
        return "; ".join(
            f"{name}={cookies[name]}" for name in self.COOKIE_NAMES if name in cookies
        )

    @classmethod
    def _is_trusted_cookie_domain(cls, domain: str) -> bool:
        return any(
            domain == suffix or domain.endswith(f".{suffix}")
            for suffix in cls.LOGIN_HOST_SUFFIXES
        )

    @staticmethod
    def _requires_verification(payload: dict) -> bool:
        for container in (payload, payload.get("data")):
            if not isinstance(container, dict):
                continue
            if any(
                container.get(name)
                for name in (
                    "captcha",
                    "verify_ticket",
                    "verify_center_decision_conf",
                )
            ):
                return True
        return False

    @staticmethod
    def _verification_error() -> PlatformLoginError:
        return PlatformLoginError(
            "抖音登录触发了平台人机或设备验证，"
            "当前私聊流程无法继续，请稍后重试或手工配置 Cookies。"
        )

    @staticmethod
    def _is_trusted_https_url(url: str, host_suffixes: tuple[str, ...]) -> bool:
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError:
            return False
        hostname = (parsed.hostname or "").lower()
        return (
            parsed.scheme == "https"
            and parsed.username is None
            and parsed.password is None
            and port in {None, 443}
            and any(
                hostname == suffix or hostname.endswith(f".{suffix}")
                for suffix in host_suffixes
            )
        )
