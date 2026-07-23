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
    provider.display_name = "小红书"
    provider.cookie_config_key = "redbook_cookies"
    service = AuthenticationService(
        {},
        provider_factories={"小红书": lambda: provider},
    )
    service.POLL_INTERVAL_SECONDS = 60
    owner = FakeEvent("adapter:private:owner")
    other = FakeEvent("adapter:private:other")
    login_task = asyncio.create_task(service.login(owner, "小红书"))
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
async def test_redbook_same_platform_login_is_exclusive():
    started = asyncio.Event()

    class WaitingRedBookProvider(FakeLoginProvider):
        display_name = "小红书"
        cookie_config_key = "redbook_cookies"

        async def poll_qr_status(self, session_key):
            started.set()
            return LoginPollResult(LoginPollState.WAITING)

    first_provider = WaitingRedBookProvider([])
    second_provider = WaitingRedBookProvider([])
    providers = [first_provider, second_provider]
    service = AuthenticationService(
        {},
        provider_factories={"小红书": lambda: providers.pop(0)},
    )
    service.POLL_INTERVAL_SECONDS = 60
    owner = FakeEvent("adapter:private:owner")
    login_task = asyncio.create_task(service.login(owner, "小红书"))
    await started.wait()

    duplicate_message = await service.login(FakeEvent(), "小红书")

    assert duplicate_message == "小红书已有登录流程正在进行，请先取消或等待结束。"
    assert second_provider.closed is True
    assert await service.cancel(owner) == "已取消当前私聊中的平台登录。"
    assert await login_task is None


@pytest.mark.asyncio
async def test_close_cancels_redbook_login_during_plugin_unload():
    started = asyncio.Event()

    class WaitingRedBookProvider(FakeLoginProvider):
        display_name = "小红书"
        cookie_config_key = "redbook_cookies"

        async def poll_qr_status(self, session_key):
            started.set()
            return LoginPollResult(LoginPollState.WAITING)

    provider = WaitingRedBookProvider([])
    service = AuthenticationService(
        {},
        provider_factories={"小红书": lambda: provider},
    )
    service.POLL_INTERVAL_SECONDS = 60
    login_task = asyncio.create_task(
        service.login(FakeEvent("adapter:private:owner"), "小红书")
    )
    await started.wait()

    await service.close()

    assert await login_task is None
    assert provider.closed is True


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
async def test_redbook_logout_restores_cookie_when_save_fails():
    config = FailingSavingConfig(redbook_cookies="web_session=session-secret")
    service = AuthenticationService(
        config,
        provider_factories={"小红书": lambda: None},
    )

    message = await service.logout("小红书")

    assert message == "Cookies 保存失败，原配置未被修改。"
    assert config["redbook_cookies"] == "web_session=session-secret"
    assert config.save_calls == 1


@pytest.mark.asyncio
async def test_redbook_login_restores_cookie_when_save_fails():
    config = FailingSavingConfig(redbook_cookies="web_session=previous-session")
    provider = FakeLoginProvider(
        [LoginPollResult(LoginPollState.SUCCESS, "web_session=new-session")]
    )
    provider.display_name = "小红书"
    provider.cookie_config_key = "redbook_cookies"
    service = AuthenticationService(
        config,
        provider_factories={"小红书": lambda: provider},
    )

    message = await service.login(FakeEvent(), "小红书")

    assert message == "Cookies 保存失败，原配置未被修改。"
    assert config["redbook_cookies"] == "web_session=previous-session"
    assert config.save_calls == 1
    assert provider.closed is True


def test_default_authentication_service_supports_all_qr_platforms():
    service = AuthenticationService(
        {
            "bilibili_cookies": "",
            "douyin_cookies": "",
            "redbook_cookies": "",
        }
    )

    assert service.supported_platforms == ("B站", "抖音", "小红书")
    assert service.status() == (
        "平台登录状态：\n- B站：未配置\n- 抖音：未配置\n- 小红书：未配置"
    )
    assert "暂不支持“douyin”" in service._unsupported_platform_message("douyin")
    assert "暂不支持“redbook”" in service._unsupported_platform_message("redbook")


def test_status_and_platform_names_only_accept_chinese():
    service = AuthenticationService(
        {"bilibili_cookies": ""},
        provider_factories={"B站": lambda: SimpleNamespace()},
    )

    assert service.status() == "平台登录状态：\n- B站：未配置"
    assert "暂不支持“bilibili”" in service._unsupported_platform_message(
        "bilibili"
    )
