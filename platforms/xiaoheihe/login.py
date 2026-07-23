"""实现小黑盒微信二维码登录与最小 Cookie 提取。"""

import re
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


class _QRCodeHTMLParser(HTMLParser):
    """收集登录页中的二维码图片候选地址。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.image_urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "img":
            return
        source = dict(attrs).get("src")
        if source and "/connect/qrcode/" in source:
            self.image_urls.append(source)


class XiaoheiheLoginProvider(PlatformLoginProvider):
    """通过小黑盒官网委托的微信 OAuth 流程建立登录态。"""

    display_name = "小黑盒"
    qr_scanner_name = "微信"
    cookie_config_key = "xiaoheihe_cookies"
    WECHAT_APP_ID = "wxced0cbce486f737e"
    WECHAT_AUTH_URL = "https://open.weixin.qq.com/connect/qrconnect"
    WECHAT_POLL_URL = "https://long.open.weixin.qq.com/connect/l/qrconnect"
    LOGIN_CALLBACK_URL = (
        "https://api.xiaoheihe.cn/account/wechat/login_redirect/v2/web_sso/"
    )
    FINAL_REDIRECT_URL = "https://login.xiaoheihe.cn/?src=1"
    QR_EXPIRES_IN_SECONDS = 300
    MAX_RESPONSE_BYTES = 128 * 1024
    MAX_QR_IMAGE_BYTES = 512 * 1024
    MAX_LOGIN_REDIRECTS = 5
    COOKIE_NAMES = ("pkey", "x_xhh_tokenid", "heybox_id")
    REQUIRED_COOKIE_NAMES = ("pkey", "x_xhh_tokenid")
    WECHAT_AUTH_HOSTS = ("open.weixin.qq.com",)
    WECHAT_POLL_HOSTS = (
        "long.open.weixin.qq.com",
        "lp.open.weixin.qq.com",
        "open.weixin.qq.com",
    )
    LOGIN_HOSTS = (
        "api.xiaoheihe.cn",
        "login.xiaoheihe.cn",
        "www.xiaoheihe.cn",
        "xiaoheihe.cn",
    )
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    _SESSION_KEY_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,256}")
    _LOGIN_CODE_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,512}")
    _QR_PATH_PATTERN = re.compile(
        r"/connect/qrcode/(?P<session>[A-Za-z0-9_-]{1,256})"
    )
    _POLL_STATUS_PATTERN = re.compile(r"wx_errcode\s*=\s*(?P<code>\d{3,5})")
    _POLL_CODE_PATTERN = re.compile(
        r"wx_code\s*=\s*['\"](?P<code>[A-Za-z0-9_-]{1,512})['\"]"
    )
    _REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})
    _VERIFICATION_MARKERS = (
        "captcha",
        "滑块",
        "人机验证",
        "设备验证",
        "安全验证",
        "访问风险",
    )

    def __init__(
        self,
        config,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._owns_client = client is None
        self._last_poll_status: int | None = None
        self._client = client or httpx.AsyncClient(
            timeout=request_timeout(config),
            follow_redirects=False,
            headers={"User-Agent": self.USER_AGENT},
        )

    async def create_qr_challenge(self) -> QRLoginChallenge:
        """创建微信 OAuth 会话并下载受信任的二维码图片。"""
        self._last_poll_status = None
        auth_url = self._build_auth_url()
        content, _ = await self._read_limited_response(
            auth_url,
            limit=self.MAX_RESPONSE_BYTES,
            allowed_hosts=self.WECHAT_AUTH_HOSTS,
        )
        self._raise_for_verification(content)
        try:
            html_text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PlatformLoginError("小黑盒返回了无效的二维码登录信息。") from exc

        parser = _QRCodeHTMLParser()
        parser.feed(html_text)
        parser.close()
        candidates: dict[str, str] = {}
        for source in parser.image_urls:
            qr_url = urljoin(self.WECHAT_AUTH_URL, source)
            if len(qr_url) > 2048 or not self._is_trusted_https_url(
                qr_url, self.WECHAT_AUTH_HOSTS
            ):
                continue
            matched = self._QR_PATH_PATTERN.fullmatch(urlsplit(qr_url).path)
            if matched is not None:
                candidates[qr_url] = matched.group("session")
        if not candidates and not parser.image_urls:
            raise PlatformLoginError("小黑盒暂时无法创建登录二维码，请稍后重试。")
        if len(candidates) != 1:
            raise PlatformLoginError("小黑盒返回了无效的二维码登录信息。")
        qr_url, session_key = next(iter(candidates.items()))

        return QRLoginChallenge(
            session_key=session_key,
            image_bytes=await self._download_qr_image(qr_url),
            expires_in_seconds=self.QR_EXPIRES_IN_SECONDS,
        )

    async def poll_qr_status(self, session_key: str) -> LoginPollResult:
        """轮询微信扫码状态，成功后完成小黑盒官方回调。"""
        if self._SESSION_KEY_PATTERN.fullmatch(session_key) is None:
            raise PlatformLoginError("小黑盒登录会话无效，请重新发起登录。")
        params: dict[str, str | int] = {"uuid": session_key}
        if self._last_poll_status is not None:
            params["last"] = self._last_poll_status
        content, _ = await self._read_limited_response(
            self.WECHAT_POLL_URL,
            limit=self.MAX_RESPONSE_BYTES,
            allowed_hosts=self.WECHAT_POLL_HOSTS,
            params=params,
        )
        self._raise_for_verification(content)
        text = content.decode("utf-8", errors="replace")
        matched = self._POLL_STATUS_PATTERN.search(text)
        if matched is None:
            raise PlatformLoginError("小黑盒登录状态查询失败，请稍后重试。")

        status_code = int(matched.group("code"))
        if status_code == 408:
            self._last_poll_status = None
            return LoginPollResult(LoginPollState.WAITING)
        if status_code == 404:
            self._last_poll_status = status_code
            return LoginPollResult(LoginPollState.SCANNED)
        if status_code == 402:
            return LoginPollResult(LoginPollState.EXPIRED)
        if status_code == 403:
            raise PlatformLoginError(
                "小黑盒登录已在微信中取消，请重新发起登录。"
            )
        if status_code == 405:
            code_match = self._POLL_CODE_PATTERN.search(text)
            if code_match is None:
                raise PlatformLoginError("小黑盒返回了无效的登录确认信息。")
            login_code = code_match.group("code")
            if self._LOGIN_CODE_PATTERN.fullmatch(login_code) is None:
                raise PlatformLoginError("小黑盒返回了无效的登录确认信息。")
            await self._complete_login_redirects(login_code)
            cookie_header = self._cookie_header()
            if not all(
                f"{name}=" in cookie_header for name in self.REQUIRED_COOKIE_NAMES
            ):
                raise PlatformLoginError(
                    "小黑盒登录成功，但响应中缺少有效登录凭据。"
                )
            return LoginPollResult(LoginPollState.SUCCESS, cookie_header)
        raise PlatformLoginError("小黑盒返回了无法识别的登录状态，请重新发起登录。")

    async def close(self) -> None:
        """关闭由适配器创建的 HTTP 客户端。"""
        if self._owns_client:
            await self._client.aclose()

    def _build_auth_url(self) -> str:
        redirect_params = {"redirect_url": self.FINAL_REDIRECT_URL}
        redirect_uri = (
            f"{self.LOGIN_CALLBACK_URL}?{urlencode(redirect_params)}"
        )
        auth_params = {
            "appid": self.WECHAT_APP_ID,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "snsapi_login",
            "state": "xiaoheihe",
        }
        return f"{self.WECHAT_AUTH_URL}?{urlencode(auth_params)}"

    async def _download_qr_image(self, url: str) -> bytes:
        content, content_type = await self._read_limited_response(
            url,
            limit=self.MAX_QR_IMAGE_BYTES,
            allowed_hosts=self.WECHAT_AUTH_HOSTS,
        )
        media_type = content_type.split(";", 1)[0].strip()
        valid_signature = content.startswith(
            b"\x89PNG\r\n\x1a\n"
        ) or content.startswith(
            b"\xff\xd8\xff"
        )
        if media_type not in {"image/png", "image/jpeg"} or not valid_signature:
            raise PlatformLoginError("小黑盒返回了无效的登录二维码图片。")
        return content

    async def _complete_login_redirects(self, login_code: str) -> None:
        callback_params = {
            "redirect_url": self.FINAL_REDIRECT_URL,
            "code": login_code,
            "state": "xiaoheihe",
        }
        current_url = (
            f"{self.LOGIN_CALLBACK_URL}?{urlencode(callback_params)}"
        )
        for _ in range(self.MAX_LOGIN_REDIRECTS + 1):
            content, _, status_code, location = await self._read_login_response(
                current_url
            )
            self._raise_for_verification(content)
            if status_code not in self._REDIRECT_STATUS_CODES:
                return
            if not location or len(location) > 2048:
                raise PlatformLoginError("小黑盒返回了无效的登录确认信息。")
            current_url = urljoin(current_url, location)
        raise PlatformLoginError("小黑盒登录确认重定向次数超过安全限制。")

    async def _read_login_response(
        self,
        url: str,
    ) -> tuple[bytes, str, int, str]:
        if not self._is_trusted_https_url(url, self.LOGIN_HOSTS):
            raise PlatformLoginError("小黑盒返回了无效的登录确认信息。")
        try:
            async with self._client.stream(
                "GET", url, follow_redirects=False
            ) as response:
                if response.status_code not in self._REDIRECT_STATUS_CODES:
                    response.raise_for_status()
                content = await self._read_response_bytes(
                    response,
                    limit=self.MAX_RESPONSE_BYTES,
                )
                return (
                    content,
                    response.headers.get("Content-Type", "").lower(),
                    response.status_code,
                    response.headers.get("Location", ""),
                )
        except PlatformLoginError:
            raise
        except httpx.HTTPError as exc:
            raise PlatformLoginError(
                "小黑盒登录确认请求失败，请稍后重试。"
            ) from exc

    async def _read_limited_response(
        self,
        url: str,
        *,
        limit: int,
        allowed_hosts: tuple[str, ...],
        **kwargs,
    ) -> tuple[bytes, str]:
        if not self._is_trusted_https_url(url, allowed_hosts):
            raise PlatformLoginError("小黑盒登录服务返回了不受信任的地址。")
        try:
            async with self._client.stream(
                "GET",
                url,
                follow_redirects=False,
                **kwargs,
            ) as response:
                if response.is_redirect:
                    raise PlatformLoginError("小黑盒登录服务返回了不安全的重定向。")
                response.raise_for_status()
                content = await self._read_response_bytes(response, limit=limit)
                return content, response.headers.get("Content-Type", "").lower()
        except PlatformLoginError:
            raise
        except httpx.HTTPError as exc:
            raise PlatformLoginError("小黑盒登录服务请求失败，请稍后重试。") from exc

    @staticmethod
    async def _read_response_bytes(
        response: httpx.Response,
        *,
        limit: int,
    ) -> bytes:
        content = bytearray()
        async for chunk in response.aiter_bytes():
            if len(content) + len(chunk) > limit:
                raise PlatformLoginError("小黑盒登录服务响应超过安全限制。")
            content.extend(chunk)
        return bytes(content)

    def _cookie_header(self) -> str:
        cookies: dict[str, str] = {}
        for cookie in self._client.cookies.jar:
            domain = str(cookie.domain or "").lstrip(".").lower()
            value = str(cookie.value or "")
            if not self._is_xiaoheihe_cookie_domain(domain):
                continue
            if (
                cookie.name in self.COOKIE_NAMES
                and value
                and len(value) <= 4096
                and ";" not in value
                and "\r" not in value
                and "\n" not in value
            ):
                cookies[cookie.name] = value
        return "; ".join(
            f"{name}={cookies[name]}" for name in self.COOKIE_NAMES if name in cookies
        )

    @staticmethod
    def _is_xiaoheihe_cookie_domain(domain: str) -> bool:
        return domain == "xiaoheihe.cn" or domain.endswith(".xiaoheihe.cn")

    @classmethod
    def _raise_for_verification(cls, content: bytes) -> None:
        text = content.decode("utf-8", errors="ignore").lower()
        if any(marker in text for marker in cls._VERIFICATION_MARKERS):
            raise PlatformLoginError(
                "小黑盒登录触发了平台人机或设备验证，"
                "当前私聊流程无法继续，请稍后重试或手工配置 Cookies。"
            )

    @staticmethod
    def _is_trusted_https_url(url: str, allowed_hosts: tuple[str, ...]) -> bool:
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError:
            return False
        return (
            parsed.scheme == "https"
            and parsed.username is None
            and parsed.password is None
            and port in {None, 443}
            and (parsed.hostname or "").lower() in allowed_hosts
        )
