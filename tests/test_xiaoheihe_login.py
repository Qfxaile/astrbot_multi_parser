import httpx
import pytest
from astrbot_multi_parser.core.authentication import (
    LoginPollState,
    PlatformLoginError,
)
from astrbot_multi_parser.platforms.xiaoheihe.login import XiaoheiheLoginProvider

QR_HTML = (
    '<html><img class="js_qr_img" '
    'src="https://open.weixin.qq.com/connect/qrcode/one-time-uuid"></html>'
)
QR_IMAGE = b"\x89PNG\r\n\x1a\nmock-image"


@pytest.mark.asyncio
async def test_xiaoheihe_qr_login_creates_wechat_challenge_without_cookie_leak():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.host == "open.weixin.qq.com"
        assert "Cookie" not in request.headers
        if request.url.path == "/connect/qrconnect":
            assert request.url.params["appid"] == XiaoheiheLoginProvider.WECHAT_APP_ID
            assert request.url.params["scope"] == "snsapi_login"
            return httpx.Response(200, request=request, text=QR_HTML)
        assert request.url.path == "/connect/qrcode/one-time-uuid"
        return httpx.Response(
            200,
            request=request,
            headers={"Content-Type": "image/png"},
            content=QR_IMAGE,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        client.cookies.set("pkey", "must-stay-on-xiaoheihe", domain=".xiaoheihe.cn")
        provider = XiaoheiheLoginProvider({}, client=client)
        challenge = await provider.create_qr_challenge()

    assert challenge.session_key == "one-time-uuid"
    assert challenge.image_bytes == QR_IMAGE
    assert challenge.expires_in_seconds == 300
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_xiaoheihe_qr_login_rejects_untrusted_qr_url():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            text=(
                '<html><img src="https://example.com/connect/qrcode/'
                'secret-one-time-token"></html>'
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = XiaoheiheLoginProvider({}, client=client)
        with pytest.raises(PlatformLoginError, match="无效的二维码") as exc_info:
            await provider.create_qr_challenge()

    assert "example.com" not in str(exc_info.value)
    assert "secret-one-time-token" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_xiaoheihe_qr_login_rejects_oversized_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            content=b"x" * (XiaoheiheLoginProvider.MAX_RESPONSE_BYTES + 1),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = XiaoheiheLoginProvider({}, client=client)
        with pytest.raises(PlatformLoginError, match="超过安全限制"):
            await provider.create_qr_challenge()


@pytest.mark.asyncio
async def test_xiaoheihe_qr_login_hides_network_error_details():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(
            "failed for https://example.com/?token=network-secret",
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = XiaoheiheLoginProvider({}, client=client)
        with pytest.raises(PlatformLoginError, match="请求失败") as exc_info:
            await provider.create_qr_challenge()

    assert "network-secret" not in str(exc_info.value)
    assert "example.com" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_xiaoheihe_qr_login_reports_verification_page():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            text="<html>captcha 人机验证</html>",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = XiaoheiheLoginProvider({}, client=client)
        with pytest.raises(PlatformLoginError, match="人机或设备验证"):
            await provider.create_qr_challenge()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected_state"),
    [
        (408, LoginPollState.WAITING),
        (404, LoginPollState.SCANNED),
        (402, LoginPollState.EXPIRED),
    ],
)
async def test_xiaoheihe_qr_login_maps_poll_states(status_code, expected_state):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "long.open.weixin.qq.com"
        assert request.url.params["uuid"] == "one-time-uuid"
        return httpx.Response(
            200,
            request=request,
            text=f"window.wx_errcode={status_code};",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = XiaoheiheLoginProvider({}, client=client)
        result = await provider.poll_qr_status("one-time-uuid")

    assert result.state == expected_state


@pytest.mark.asyncio
async def test_xiaoheihe_qr_login_reports_wechat_rejection():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            text="window.wx_errcode=403;",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = XiaoheiheLoginProvider({}, client=client)
        with pytest.raises(PlatformLoginError, match="微信中取消"):
            await provider.poll_qr_status("one-time-uuid")


@pytest.mark.asyncio
async def test_xiaoheihe_qr_login_sends_scanned_state_to_next_poll():
    poll_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal poll_count
        poll_count += 1
        if poll_count == 1:
            assert "last" not in request.url.params
            status_code = 404
        else:
            assert request.url.params["last"] == "404"
            status_code = 408
        return httpx.Response(
            200,
            request=request,
            text=f"window.wx_errcode={status_code};",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = XiaoheiheLoginProvider({}, client=client)
        first_result = await provider.poll_qr_status("one-time-uuid")
        second_result = await provider.poll_qr_status("one-time-uuid")

    assert first_result.state == LoginPollState.SCANNED
    assert second_result.state == LoginPollState.WAITING


@pytest.mark.asyncio
async def test_xiaoheihe_qr_login_collects_only_expected_domain_cookies():
    requested_hosts = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_hosts.append(request.url.host)
        if request.url.host == "long.open.weixin.qq.com":
            return httpx.Response(
                200,
                request=request,
                text=(
                    "window.wx_errcode=405;"
                    "window.wx_code='one-time-oauth-code';"
                ),
            )
        if request.url.host == "api.xiaoheihe.cn":
            assert request.url.params["code"] == "one-time-oauth-code"
            assert request.url.params["state"] == "xiaoheihe"
            return httpx.Response(
                302,
                request=request,
                headers=[
                    ("Location", "https://login.xiaoheihe.cn/?src=1"),
                    (
                        "Set-Cookie",
                        "pkey=session-secret; Domain=.xiaoheihe.cn; Path=/",
                    ),
                    (
                        "Set-Cookie",
                        "x_xhh_tokenid=Bdevice-secret; "
                        "Domain=.xiaoheihe.cn; Path=/",
                    ),
                    (
                        "Set-Cookie",
                        "not_needed=ignore-me; Domain=.xiaoheihe.cn; Path=/",
                    ),
                ],
            )
        assert request.url.host == "login.xiaoheihe.cn"
        return httpx.Response(
            200,
            request=request,
            headers={
                "Set-Cookie": (
                    "heybox_id=123456; Domain=.xiaoheihe.cn; Path=/"
                )
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        client.cookies.set("foreign", "must-not-save", domain="example.com")
        provider = XiaoheiheLoginProvider({}, client=client)
        result = await provider.poll_qr_status("one-time-uuid")

    assert result.state == LoginPollState.SUCCESS
    assert result.cookie_header == (
        "pkey=session-secret; x_xhh_tokenid=Bdevice-secret; heybox_id=123456"
    )
    assert "not_needed" not in result.cookie_header
    assert "foreign" not in result.cookie_header
    assert requested_hosts == [
        "long.open.weixin.qq.com",
        "api.xiaoheihe.cn",
        "login.xiaoheihe.cn",
    ]


@pytest.mark.asyncio
async def test_xiaoheihe_qr_login_rejects_untrusted_success_redirect():
    requested_hosts = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_hosts.append(request.url.host)
        if request.url.host == "long.open.weixin.qq.com":
            return httpx.Response(
                200,
                request=request,
                text=(
                    "window.wx_errcode=405;"
                    "window.wx_code='oauth-code-secret';"
                ),
            )
        return httpx.Response(
            302,
            request=request,
            headers={"Location": "https://example.com/steal-login"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = XiaoheiheLoginProvider({}, client=client)
        with pytest.raises(PlatformLoginError, match="无效的登录确认") as exc_info:
            await provider.poll_qr_status("one-time-uuid")

    assert requested_hosts == ["long.open.weixin.qq.com", "api.xiaoheihe.cn"]
    assert "oauth-code-secret" not in str(exc_info.value)
    assert "example.com" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_xiaoheihe_qr_login_reports_callback_verification_page():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "long.open.weixin.qq.com":
            return httpx.Response(
                200,
                request=request,
                text=(
                    "window.wx_errcode=405;"
                    "window.wx_code='oauth-code-secret';"
                ),
            )
        return httpx.Response(
            200,
            request=request,
            text="<html>设备验证 captcha</html>",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = XiaoheiheLoginProvider({}, client=client)
        with pytest.raises(PlatformLoginError, match="人机或设备验证") as exc_info:
            await provider.poll_qr_status("one-time-uuid")

    assert "oauth-code-secret" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_xiaoheihe_qr_login_rejects_missing_required_cookie():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "long.open.weixin.qq.com":
            return httpx.Response(
                200,
                request=request,
                text=(
                    "window.wx_errcode=405;"
                    "window.wx_code='oauth-code-secret';"
                ),
            )
        return httpx.Response(
            200,
            request=request,
            headers={
                "Set-Cookie": (
                    "x_xhh_tokenid=Bdevice-secret; "
                    "Domain=.xiaoheihe.cn; Path=/"
                )
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        client.cookies.set("pkey", "foreign-secret", domain="example.com")
        provider = XiaoheiheLoginProvider({}, client=client)
        with pytest.raises(PlatformLoginError, match="缺少有效登录凭据") as exc_info:
            await provider.poll_qr_status("one-time-uuid")

    assert "foreign-secret" not in str(exc_info.value)
    assert "Bdevice-secret" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_xiaoheihe_qr_login_rejects_unknown_status_without_secret_leak():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            text="window.wx_errcode=999;",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = XiaoheiheLoginProvider({}, client=client)
        with pytest.raises(PlatformLoginError, match="无法识别") as exc_info:
            await provider.poll_qr_status("secret-one-time-uuid")

    assert "secret-one-time-uuid" not in str(exc_info.value)
