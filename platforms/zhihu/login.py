"""实现知乎二维码登录与 Cookie 提取。"""

import json
import re
from io import BytesIO
from urllib.parse import urlsplit

import httpx
import qrcode

from ...core.authentication import (
    LoginPollResult,
    LoginPollState,
    PlatformLoginError,
    PlatformLoginProvider,
    QRLoginChallenge,
)
from ...core.http import request_timeout


class ZhihuLoginProvider(PlatformLoginProvider):
    """通过知乎官方网页二维码接口建立管理员登录态。"""

    display_name = "知乎"
    cookie_config_key = "zhihu_cookies"
    QR_GENERATE_URL = "https://www.zhihu.com/api/v3/account/api/login/qrcode"
    QR_POLL_URL_PREFIX = (
        "https://www.zhihu.com/api/v3/account/api/login/qrcode"
    )
    QR_EXPIRES_IN_SECONDS = 180
    MAX_RESPONSE_BYTES = 64 * 1024
    COOKIE_NAMES = ("z_c0", "d_c0")
    LOGIN_HOST_SUFFIXES = ("zhihu.com",)
    RISK_CONTROL_CODES = frozenset({40321, 410001})
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )
    _SESSION_KEY_PATTERN = re.compile(r"[A-Za-z0-9._~=-]{1,512}")

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
                "Referer": "https://www.zhihu.com/signin",
                "Origin": "https://www.zhihu.com",
            },
        )

    async def create_qr_challenge(self) -> QRLoginChallenge:
        """创建二维码会话，并在内存中渲染受信任的登录链接。"""
        payload = await self._request_payload("POST", self.QR_GENERATE_URL)
        data = self._payload_data(payload)
        login_url = str(data.get("link") or "")
        session_key = str(data.get("token") or "")
        if (
            len(login_url) > 2048
            or not self._is_trusted_https_url(login_url)
            or self._SESSION_KEY_PATTERN.fullmatch(session_key) is None
        ):
            raise PlatformLoginError("知乎返回了无效的二维码登录信息。")

        return QRLoginChallenge(
            session_key=session_key,
            image_bytes=self._render_qr_code(login_url),
            expires_in_seconds=self.QR_EXPIRES_IN_SECONDS,
        )

    async def poll_qr_status(self, session_key: str) -> LoginPollResult:
        """轮询扫码状态，成功时提取知乎域的最小 Cookie 集合。"""
        if self._SESSION_KEY_PATTERN.fullmatch(session_key) is None:
            raise PlatformLoginError("知乎登录会话无效，请重新发起登录。")

        payload = await self._request_payload(
            "GET",
            f"{self.QR_POLL_URL_PREFIX}/{session_key}/scan_info",
        )
        data = self._payload_data(payload)
        if data.get("accessToken") or data.get("access_token"):
            cookie_header = self._cookie_header()
            if not cookie_header.startswith("z_c0="):
                raise PlatformLoginError(
                    "知乎登录成功，但响应中缺少有效登录凭据。"
                )
            return LoginPollResult(LoginPollState.SUCCESS, cookie_header)

        status = str(data.get("status") if "status" in data else "").lower()
        if status == "0":
            return LoginPollResult(LoginPollState.WAITING)
        if status == "1":
            return LoginPollResult(LoginPollState.SCANNED)
        if status == "5":
            # 官方网页会把新令牌渲染为新二维码；私聊无法替换已发送图片。
            return LoginPollResult(LoginPollState.EXPIRED)
        raise PlatformLoginError("知乎返回了无法识别的登录状态，请重新发起登录。")

    async def close(self) -> None:
        """关闭由适配器创建的 HTTP 客户端。"""
        if self._owns_client:
            await self._client.aclose()

    async def _request_payload(self, method: str, url: str) -> dict:
        try:
            async with self._client.stream(
                method,
                url,
                follow_redirects=False,
            ) as response:
                if response.is_redirect:
                    raise PlatformLoginError(
                        "知乎登录服务返回了不安全的重定向。"
                    )
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(content) + len(chunk) > self.MAX_RESPONSE_BYTES:
                        raise PlatformLoginError("知乎登录服务响应超过安全限制。")
                    content.extend(chunk)
                content_type = response.headers.get("Content-Type", "").lower()
                if response.status_code in {401, 403, 429}:
                    raise self._verification_error()
                response.raise_for_status()

            stripped = bytes(content).lstrip()
            if "text/html" in content_type or stripped.startswith(b"<"):
                raise self._verification_error()
            payload = json.loads(content)
        except PlatformLoginError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise PlatformLoginError("知乎登录服务请求失败，请稍后重试。") from exc

        if not isinstance(payload, dict):
            raise PlatformLoginError("知乎登录服务返回了无效响应。")
        if self._requires_verification(payload):
            raise self._verification_error()
        return payload

    @staticmethod
    def _payload_data(payload: dict) -> dict:
        data = payload.get("data")
        return data if isinstance(data, dict) else payload

    def _cookie_header(self) -> str:
        cookies: dict[str, str] = {}
        for cookie in self._client.cookies.jar:
            domain = str(cookie.domain or "").lstrip(".").lower()
            if not self._is_trusted_cookie_domain(domain):
                continue
            value = str(cookie.value or "")
            if (
                cookie.name in self.COOKIE_NAMES
                and value
                and not any(character in value for character in ";\r\n")
            ):
                cookies[cookie.name] = value
        return "; ".join(
            f"{name}={cookies[name]}" for name in self.COOKIE_NAMES if name in cookies
        )

    @classmethod
    def _is_trusted_cookie_domain(cls, domain: str) -> bool:
        return any(
            domain == suffix or domain.endswith(f".{suffix}")
            for suffix in cls.LOGIN_HOST_SUFFIXES
        )

    @classmethod
    def _requires_verification(cls, payload: dict) -> bool:
        containers = [payload]
        for key in ("data", "error"):
            value = payload.get(key)
            if isinstance(value, dict):
                containers.append(value)
        for container in containers:
            code = container.get("code")
            try:
                if int(code) in cls.RISK_CONTROL_CODES:
                    return True
            except (TypeError, ValueError):
                pass
            if any(
                container.get(name)
                for name in (
                    "captcha",
                    "challenge",
                    "needCaptcha",
                    "needDeviceVerify",
                    "needVerification",
                    "unhuman",
                    "verifyTicket",
                    "verify_ticket",
                )
            ):
                return True
            for name in ("detail", "error", "message"):
                message = container.get(name)
                if not isinstance(message, str):
                    continue
                normalized = message.lower()
                if any(
                    marker in normalized
                    for marker in (
                        "captcha",
                        "challenge",
                        "device verify",
                        "risk control",
                        "unhuman",
                        "人机验证",
                        "安全验证",
                        "设备验证",
                    )
                ):
                    return True
        return False

    @staticmethod
    def _verification_error() -> PlatformLoginError:
        return PlatformLoginError(
            "知乎登录触发了平台人机或设备验证，"
            "当前私聊流程无法继续，请稍后重试或手工配置 Cookies。"
        )

    @classmethod
    def _is_trusted_https_url(cls, url: str) -> bool:
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
                for suffix in cls.LOGIN_HOST_SUFFIXES
            )
        )

    @staticmethod
    def _render_qr_code(value: str) -> bytes:
        qr_code = qrcode.QRCode(
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=8,
            border=4,
        )
        qr_code.add_data(value)
        qr_code.make(fit=True)
        image = qr_code.make_image(fill_color="black", back_color="white")
        output = BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()
