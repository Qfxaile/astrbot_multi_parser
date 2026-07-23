import asyncio
from types import SimpleNamespace

import pytest
from astrbot.api.message_components import Image, Plain
from astrbot_multi_parser.core.authentication import (
    LoginPollResult,
    LoginPollState,
    PlatformLoginProvider,
    QRLoginChallenge,
)
from astrbot_multi_parser.services.authentication import AuthenticationService


class SavingConfig(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.save_calls = 0

    def save_config(self):
        self.save_calls += 1


class FailingSavingConfig(SavingConfig):
    def save_config(self):
        super().save_config()
        raise RuntimeError("disk failure")


class FakeEvent:
    def __init__(self, session_id="adapter:private:admin"):
        self.unified_msg_origin = session_id
        self.sent = []

    async def send(self, message):
        self.sent.append(list(message.chain))


class FakeLoginProvider(PlatformLoginProvider):
    display_name = "B站"
    cookie_config_key = "bilibili_cookies"

    def __init__(self, results):
        self.results = list(results)
        self.closed = False

    async def create_qr_challenge(self):
        return QRLoginChallenge("secret-key", b"png-data", 30)

    async def poll_qr_status(self, session_key):
        assert session_key == "secret-key"
        return self.results.pop(0)

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_login_sends_qr_and_saves_cookie_without_echoing_secret():
    config = SavingConfig()
    provider = FakeLoginProvider(
        [
            LoginPollResult(LoginPollState.SCANNED),
            LoginPollResult(
                LoginPollState.SUCCESS,
                "SESSDATA=session-secret; bili_jct=csrf-secret",
            ),
        ]
    )
    service = AuthenticationService(
        config,
        provider_factories={"B站": lambda: provider},
    )
    service.POLL_INTERVAL_SECONDS = 0
    event = FakeEvent()

    message = await service.login(event, "B站")

    assert message == "B站登录成功，Cookies 已保存。"
    assert config["bilibili_cookies"].startswith("SESSDATA=")
    assert config.save_calls == 1
    assert provider.closed is True
    assert isinstance(event.sent[0][0], Plain)
    assert isinstance(event.sent[0][1], Image)
    assert event.sent[0][1].file == "base64://cG5nLWRhdGE="
    visible_text = "".join(
        component.text
        for chain in event.sent
        for component in chain
        if isinstance(component, Plain)
    )
    assert "secret-key" not in visible_text
    assert "session-secret" not in visible_text


@pytest.mark.asyncio
async def test_cancel_only_stops_login_from_same_private_session():
    started = asyncio.Event()

    class WaitingProvider(FakeLoginProvider):
        async def poll_qr_status(self, session_key):
            started.set()
            return LoginPollResult(LoginPollState.WAITING)

    provider = WaitingProvider([])
    service = AuthenticationService(
        {},
        provider_factories={"B站": lambda: provider},
    )
    service.POLL_INTERVAL_SECONDS = 60
    owner = FakeEvent("adapter:private:owner")
    other = FakeEvent("adapter:private:other")
    login_task = asyncio.create_task(service.login(owner, "B站"))
    await started.wait()

    assert await service.cancel(other) == "当前私聊没有进行中的平台登录。"
    assert await service.cancel(owner) == "已取消当前私聊中的平台登录。"
    assert await login_task is None
    assert provider.closed is True


@pytest.mark.asyncio
async def test_logout_clears_cookie_and_saves_config():
    config = SavingConfig(bilibili_cookies="SESSDATA=session-secret")
    service = AuthenticationService(config, provider_factories={"B站": lambda: None})

    message = await service.logout("B站")

    assert message == "B站已退出登录，Cookies 已清除。"
    assert config["bilibili_cookies"] == ""
    assert config.save_calls == 1


@pytest.mark.asyncio
async def test_douyin_same_platform_login_is_exclusive():
    started = asyncio.Event()

    class WaitingDouyinProvider(FakeLoginProvider):
        display_name = "抖音"
        cookie_config_key = "douyin_cookies"

        async def poll_qr_status(self, session_key):
            started.set()
            return LoginPollResult(LoginPollState.WAITING)

    first_provider = WaitingDouyinProvider([])
    second_provider = WaitingDouyinProvider([])
    providers = [first_provider, second_provider]
    service = AuthenticationService(
        {},
        provider_factories={"抖音": lambda: providers.pop(0)},
    )
    service.POLL_INTERVAL_SECONDS = 60
    owner = FakeEvent("adapter:private:owner")
    login_task = asyncio.create_task(service.login(owner, "抖音"))
    await started.wait()

    duplicate_message = await service.login(FakeEvent(), "抖音")

    assert duplicate_message == "抖音已有登录流程正在进行，请先取消或等待结束。"
    assert second_provider.closed is True
    assert await service.cancel(owner) == "已取消当前私聊中的平台登录。"
    assert await login_task is None


@pytest.mark.asyncio
async def test_douyin_logout_restores_cookie_when_save_fails():
    config = FailingSavingConfig(douyin_cookies="sessionid=session-secret")
    service = AuthenticationService(
        config,
        provider_factories={"抖音": lambda: None},
    )

    message = await service.logout("抖音")

    assert message == "Cookies 保存失败，原配置未被修改。"
    assert config["douyin_cookies"] == "sessionid=session-secret"
    assert config.save_calls == 1


@pytest.mark.asyncio
async def test_wechat_same_platform_login_is_exclusive_and_cancel_is_private():
    started = asyncio.Event()

    class WaitingWeChatProvider(FakeLoginProvider):
        display_name = "微信"
        cookie_config_key = "wechat_yuanbao_cookies"

        async def poll_qr_status(self, session_key):
            started.set()
            return LoginPollResult(LoginPollState.WAITING)

    first_provider = WaitingWeChatProvider([])
    second_provider = WaitingWeChatProvider([])
    providers = [first_provider, second_provider]
    service = AuthenticationService(
        {},
        provider_factories={"微信": lambda: providers.pop(0)},
    )
    service.POLL_INTERVAL_SECONDS = 60
    owner = FakeEvent("adapter:private:wechat-owner")
    other = FakeEvent("adapter:private:other")
    login_task = asyncio.create_task(service.login(owner, "微信"))
    await started.wait()

    duplicate_message = await service.login(other, "微信")

    assert duplicate_message == "微信已有登录流程正在进行，请先取消或等待结束。"
    assert second_provider.closed is True
    assert await service.cancel(other) == "当前私聊没有进行中的平台登录。"
    assert await service.cancel(owner) == "已取消当前私聊中的平台登录。"
    assert await login_task is None


@pytest.mark.asyncio
async def test_wechat_logout_restores_cookie_when_save_fails():
    original_cookie = "hy_user=user-secret; hy_token=token-secret"
    config = FailingSavingConfig(wechat_yuanbao_cookies=original_cookie)
    service = AuthenticationService(
        config,
        provider_factories={"微信": lambda: None},
    )

    message = await service.logout("微信")

    assert message == "Cookies 保存失败，原配置未被修改。"
    assert config["wechat_yuanbao_cookies"] == original_cookie
    assert config.save_calls == 1


@pytest.mark.asyncio
async def test_wechat_login_restores_cookie_when_save_fails_without_leaking_it():
    original_cookie = "hy_user=old-user; hy_token=old-token"

    class SuccessfulWeChatProvider(FakeLoginProvider):
        display_name = "微信"
        cookie_config_key = "wechat_yuanbao_cookies"

    config = FailingSavingConfig(wechat_yuanbao_cookies=original_cookie)
    provider = SuccessfulWeChatProvider(
        [
            LoginPollResult(
                LoginPollState.SUCCESS,
                "hy_user=new-user; hy_token=new-token",
            )
        ]
    )
    service = AuthenticationService(
        config,
        provider_factories={"微信": lambda: provider},
    )

    message = await service.login(FakeEvent(), "微信")

    assert message == "Cookies 保存失败，原配置未被修改。"
    assert config["wechat_yuanbao_cookies"] == original_cookie
    assert config.save_calls == 1
    assert provider.closed is True
    assert "old-user" not in message
    assert "new-user" not in message


def test_default_authentication_service_supports_all_qr_platforms():
    service = AuthenticationService(
        {
            "bilibili_cookies": "",
            "douyin_cookies": "",
            "wechat_yuanbao_cookies": "",
        }
    )

    assert service.supported_platforms == ("B站", "抖音", "微信")
    assert service.status() == (
        "平台登录状态：\n- B站：未配置\n- 抖音：未配置\n- 微信：未配置"
    )
    assert "暂不支持“douyin”" in service._unsupported_platform_message("douyin")
    assert "暂不支持“wechat”" in service._unsupported_platform_message("wechat")


def test_status_and_platform_names_only_accept_chinese():
    service = AuthenticationService(
        {"bilibili_cookies": ""},
        provider_factories={"B站": lambda: SimpleNamespace()},
    )

    assert service.status() == "平台登录状态：\n- B站：未配置"
    assert "暂不支持“bilibili”" in service._unsupported_platform_message(
        "bilibili"
    )
