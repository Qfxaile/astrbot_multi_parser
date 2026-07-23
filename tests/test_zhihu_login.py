import httpx
import pytest
from astrbot_multi_parser.core.authentication import (
    LoginPollState,
    PlatformLoginError,
)
from astrbot_multi_parser.platforms.zhihu.login import ZhihuLoginProvider


@pytest.mark.asyncio
async def test_zhihu_qr_login_creates_challenge_from_trusted_url():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v3/account/api/login/qrcode"
        return httpx.Response(
            200,
            request=request,
            json={
                "token": "one-time-token",
                "link": "https://www.zhihu.com/account/scan/login",
                "expiresAt": 180,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = ZhihuLoginProvider({}, client=client)
        challenge = await provider.create_qr_challenge()

    assert challenge.session_key == "one-time-token"
    assert challenge.image_bytes.startswith(b"\x89PNG")
    assert challenge.expires_in_seconds == 180


@pytest.mark.asyncio
async def test_zhihu_qr_login_collects_only_expected_domain_cookies():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/one-time-token/scan_info")
        return httpx.Response(
            200,
            request=request,
            headers=[
                (
                    "Set-Cookie",
                    "z_c0=session-secret; Domain=.zhihu.com; Path=/",
                ),
                (
                    "Set-Cookie",
                    "d_c0=device-secret; Domain=.zhihu.com; Path=/",
                ),
                (
                    "Set-Cookie",
                    "_xsrf=not-needed; Domain=.zhihu.com; Path=/",
                ),
            ],
            json={"accessToken": "must-not-save"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        client.cookies.set("z_c0", "foreign-secret", domain="example.com")
        client.cookies.set("foreign", "must-not-save", domain="example.com")
        provider = ZhihuLoginProvider({}, client=client)
        result = await provider.poll_qr_status("one-time-token")

    assert result.state == LoginPollState.SUCCESS
    assert result.cookie_header == "z_c0=session-secret; d_c0=device-secret"
    assert "_xsrf" not in result.cookie_header
    assert "foreign" not in result.cookie_header
    assert "must-not-save" not in result.cookie_header


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "expected_state"),
    [
        ({"status": 0}, LoginPollState.WAITING),
        ({"status": 1}, LoginPollState.SCANNED),
        (
            {
                "status": 5,
                "newToken": {
                    "token": "replacement-secret",
                    "link": "https://www.zhihu.com/account/scan/replacement",
                },
            },
            LoginPollState.EXPIRED,
        ),
    ],
)
async def test_zhihu_qr_login_maps_poll_states(payload, expected_state):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, request=request, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = ZhihuLoginProvider({}, client=client)
        result = await provider.poll_qr_status("one-time-token")

    assert result.state == expected_state


@pytest.mark.asyncio
async def test_zhihu_qr_login_rejects_unknown_status_without_leaking_token():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            json={"status": 9, "token": "response-secret"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = ZhihuLoginProvider({}, client=client)
        with pytest.raises(PlatformLoginError, match="无法识别") as exc_info:
            await provider.poll_qr_status("request-secret")

    assert "request-secret" not in str(exc_info.value)
    assert "response-secret" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_zhihu_qr_login_rejects_untrusted_qr_url_without_leaking_token():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            json={
                "token": "secret-one-time-token",
                "link": "https://example.com/steal-login",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = ZhihuLoginProvider({}, client=client)
        with pytest.raises(PlatformLoginError, match="无效的二维码") as exc_info:
            await provider.create_qr_challenge()

    assert "secret-one-time-token" not in str(exc_info.value)
    assert "example.com" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_zhihu_qr_login_rejects_oversized_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            content=b"x" * (ZhihuLoginProvider.MAX_RESPONSE_BYTES + 1),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = ZhihuLoginProvider({}, client=client)
        with pytest.raises(PlatformLoginError, match="超过安全限制"):
            await provider.create_qr_challenge()


@pytest.mark.asyncio
async def test_zhihu_qr_login_rejects_redirect_without_following_target():
    requested_hosts = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_hosts.append(request.url.host)
        return httpx.Response(
            302,
            request=request,
            headers={"Location": "https://example.com/private"},
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
    ) as client:
        provider = ZhihuLoginProvider({}, client=client)
        with pytest.raises(PlatformLoginError, match="不安全的重定向"):
            await provider.create_qr_challenge()

    assert requested_hosts == ["www.zhihu.com"]


@pytest.mark.asyncio
async def test_zhihu_qr_login_reports_platform_verification_page():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            headers={"Content-Type": "text/html; charset=utf-8"},
            text="<html>captcha verify security</html>",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = ZhihuLoginProvider({}, client=client)
        with pytest.raises(PlatformLoginError, match="人机或设备验证"):
            await provider.create_qr_challenge()


@pytest.mark.asyncio
async def test_zhihu_qr_login_reports_json_verification_without_leaking_ticket():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            json={
                "error": {
                    "code": 40321,
                    "verify_ticket": "ticket-secret",
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = ZhihuLoginProvider({}, client=client)
        with pytest.raises(PlatformLoginError, match="人机或设备验证") as exc_info:
            await provider.create_qr_challenge()

    assert "ticket-secret" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_zhihu_qr_login_hides_network_error_details():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(
            "failed for https://example.com/?token=network-secret",
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = ZhihuLoginProvider({}, client=client)
        with pytest.raises(PlatformLoginError, match="请求失败") as exc_info:
            await provider.create_qr_challenge()

    assert "network-secret" not in str(exc_info.value)
    assert "example.com" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_zhihu_qr_login_requires_z_c0_without_leaking_access_token():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            json={"accessToken": "access-token-secret"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        client.cookies.set("d_c0", "device-secret", domain=".zhihu.com")
        provider = ZhihuLoginProvider({}, client=client)
        with pytest.raises(PlatformLoginError, match="缺少有效登录凭据") as exc_info:
            await provider.poll_qr_status("one-time-token")

    assert "access-token-secret" not in str(exc_info.value)
    assert "device-secret" not in str(exc_info.value)
