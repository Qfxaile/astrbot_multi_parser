from types import SimpleNamespace

import httpx
import pytest
from astrbot.api.message_components import Image, Node, Nodes, Plain, Record, Video
from astrbot_multi_parser import main
from astrbot_multi_parser.core.http import CookieAccessError
from astrbot_multi_parser.main import MultiParserPlugin, VideoSizeInfo
from astrbot_multi_parser.models import OrderedContent, ParseResult


class FakeParser:
    name = "fake"

    def __init__(self, result: ParseResult):
        self.result = result

    async def match(self, context):
        return True

    async def parse(self, context):
        return self.result


class FailingParser:
    name = "fake"

    async def match(self, context):
        return True

    async def parse(self, context):
        raise CookieAccessError("测试平台", configured=False)


class SavingConfig(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.save_calls = 0

    def save_config(self):
        self.save_calls += 1


class FakeBot:
    def __init__(self, failure=None):
        self.failure = failure
        self.actions = []

    async def call_action(self, action, **params):
        self.actions.append((action, params))
        if self.failure is not None:
            raise self.failure


class FakeEvent:
    def __init__(
        self,
        sender_id=123,
        sender_name="",
        sender=None,
        raw_message=None,
        platform_name="aiocqhttp",
        forward_failure_limit=None,
        bot=None,
    ):
        self.sender_id = sender_id
        self.sender_name = sender_name
        self.platform_name = platform_name
        self.forward_failure_limit = forward_failure_limit
        self.bot = bot
        self.sent = []
        self.forward_attempt_sizes = []
        self.message_obj = SimpleNamespace(
            raw_message=(
                {"sender": sender or {}} if raw_message is None else raw_message
            ),
            message_id="",
        )

    def get_sender_id(self):
        return self.sender_id

    def get_sender_name(self):
        return self.sender_name

    def get_platform_name(self):
        if self.platform_name == "__raise__":
            raise RuntimeError("platform unavailable")
        return self.platform_name

    def chain_result(self, chain):
        return chain

    def plain_result(self, text):
        return [Plain(text)]

    async def send(self, message):
        chain = list(message.chain)
        if len(chain) == 1 and isinstance(chain[0], Nodes):
            node_count = len(chain[0].nodes)
            self.forward_attempt_sizes.append(node_count)
            if (
                self.forward_failure_limit is not None
                and node_count > self.forward_failure_limit
            ):
                raise RuntimeError("forward rejected")
        self.sent.append(chain)


def make_plugin(result: ParseResult, **config):
    plugin = MultiParserPlugin.__new__(MultiParserPlugin)
    plugin.config = {
        "enabled_platforms": ["fake"],
        "enable_parse_reaction": False,
        "send_video_by_url": True,
        **config,
    }
    plugin.parsers = {"fake": FakeParser(result)}
    return plugin


def test_plugin_registers_all_supported_parsers():
    plugin = MultiParserPlugin(None, {"enabled_platforms": []})

    assert set(plugin.parsers) == {
        "bilibili",
        "douyin",
        "redbook",
        "tieba",
        "weibo",
        "xiaoheihe",
        "zhihu",
    }


def test_plugin_migrates_legacy_enabled_platforms_once():
    config = SavingConfig(
        enabled_platforms=["bilibili", "zhihu"],
        platform_switches={
            "bilibili": True,
            "douyin": True,
            "redbook": True,
            "tieba": True,
            "weibo": True,
            "xiaoheihe": True,
            "zhihu": True,
        },
        platform_switches_migrated=False,
    )

    plugin = MultiParserPlugin(None, config)

    assert config["platform_switches"] == {
        "bilibili": True,
        "douyin": False,
        "redbook": False,
        "tieba": False,
        "weibo": False,
        "xiaoheihe": False,
        "zhihu": True,
    }
    assert config["platform_switches_migrated"] is True
    assert config.save_calls == 1
    assert plugin._enabled_parsers() == [
        plugin.parsers["bilibili"],
        plugin.parsers["zhihu"],
    ]


def test_plugin_respects_platform_switches_after_migration():
    config = SavingConfig(
        enabled_platforms=[
            "bilibili",
            "douyin",
            "redbook",
            "tieba",
            "weibo",
            "xiaoheihe",
            "zhihu",
        ],
        platform_switches={
            "bilibili": False,
            "douyin": True,
            "redbook": False,
            "tieba": False,
            "weibo": False,
            "xiaoheihe": True,
            "zhihu": False,
        },
        platform_switches_migrated=True,
    )

    plugin = MultiParserPlugin(None, config)

    assert config.save_calls == 0
    assert plugin._enabled_parsers() == [
        plugin.parsers["douyin"],
        plugin.parsers["xiaoheihe"],
    ]


async def collect_results(monkeypatch, result, event=None, **config):
    monkeypatch.setattr(
        main, "extract_context", lambda event: SimpleNamespace(combined_text="url")
    )
    plugin = make_plugin(result, **config)
    target_event = event or FakeEvent()
    yielded = [item async for item in plugin.handle_parse(target_event)]
    return [*target_event.sent, *yielded]


async def collect_plugin_results(plugin, event):
    yielded = [item async for item in plugin.handle_parse(event)]
    return [*event.sent, *yielded]


@pytest.mark.asyncio
async def test_handle_parse_outputs_cookie_failure_without_generic_prefix(monkeypatch):
    monkeypatch.setattr(
        main, "extract_context", lambda event: SimpleNamespace(combined_text="url")
    )
    plugin = make_plugin(ParseResult(platform="fake"))
    plugin.parsers = {"fake": FailingParser()}

    messages = await collect_plugin_results(plugin, FakeEvent())

    assert messages[0][0].text == (
        "测试平台内容获取失败，可能需要配置 Cookies，请在插件配置中填写后重试。"
    )
    assert "fake 解析失败" not in messages[0][0].text


@pytest.mark.asyncio
async def test_handle_parse_cleans_temporary_images_after_send(monkeypatch, tmp_path):
    image_path = tmp_path / "original.webp"
    image_path.write_bytes(b"original-image")
    result = ParseResult(
        platform="test",
        image_urls=[str(image_path)],
        temporary_files=[image_path],
    )

    messages = await collect_results(monkeypatch, result)

    assert messages[0][0].file == image_path.resolve().as_uri()
    assert messages[0][0].path == str(image_path.resolve())
    assert not image_path.exists()
    assert result.temporary_files == []


@pytest.mark.asyncio
async def test_two_images_keep_legacy_info_chain_order(monkeypatch):
    result = ParseResult(
        platform="test",
        title="标题",
        cover_urls=["base64://cover"],
        image_urls=["base64://image"],
    )

    messages = await collect_results(monkeypatch, result)

    assert len(messages) == 1
    assert [type(component) for component in messages[0]] == [Image, Image, Plain]
    assert [component.file for component in messages[0][:2]] == [
        "base64://cover",
        "base64://image",
    ]


@pytest.mark.asyncio
async def test_exactly_three_images_are_sent_as_one_forward_message(
    monkeypatch,
):
    result = ParseResult(
        platform="test",
        title="标题",
        image_urls=["base64://1", "base64://2", "base64://3"],
    )

    messages = await collect_results(monkeypatch, result)

    assert len(messages) == 1
    assert len(messages[0]) == 1
    assert isinstance(messages[0][0], Nodes)
    nodes = messages[0][0].nodes
    assert len(nodes) == 4
    assert all(isinstance(node, Node) and len(node.content) == 1 for node in nodes)
    assert all(isinstance(node.content[0], Image) for node in nodes[:3])
    assert isinstance(nodes[3].content[0], Plain)
    assert nodes[3].content[0].text == "标题"


@pytest.mark.asyncio
async def test_four_images_create_four_nodes(monkeypatch):
    result = ParseResult(
        platform="test",
        image_urls=[f"base64://{index}" for index in range(4)],
    )

    messages = await collect_results(monkeypatch, result)

    assert len(messages) == 1
    assert isinstance(messages[0][0], Nodes)
    assert [node.content[0].file for node in messages[0][0].nodes] == [
        "base64://0",
        "base64://1",
        "base64://2",
        "base64://3",
    ]


@pytest.mark.asyncio
async def test_adjacent_forward_text_is_merged_with_newlines(monkeypatch):
    contents = [
        OrderedContent("text", "第一段\n"),
        OrderedContent("text", "\n第二段"),
        OrderedContent("image", "base64://image"),
        OrderedContent("text", "第三段"),
        OrderedContent("text", "第四段"),
    ]

    messages = await collect_results(
        monkeypatch,
        ParseResult(platform="test", ordered_contents=contents),
        forward_mode="always",
    )

    nodes = messages[0][0].nodes
    assert [type(node.content[0]) for node in nodes] == [Plain, Image, Plain]
    assert nodes[0].content[0].text == "第一段\n第二段"
    assert nodes[1].content[0].file == "base64://image"
    assert nodes[2].content[0].text == "第三段\n第四段"


@pytest.mark.asyncio
async def test_forward_is_split_at_official_node_limit(monkeypatch):
    result = ParseResult(
        platform="test",
        image_urls=[f"base64://{index}" for index in range(101)],
    )

    messages = await collect_results(
        monkeypatch,
        result,
        forward_mode="always",
    )

    assert [len(message[0].nodes) for message in messages] == [51, 50]
    assert [
        node.content[0].file for message in messages for node in message[0].nodes
    ] == [f"base64://{index}" for index in range(101)]


@pytest.mark.asyncio
async def test_rejected_forward_batch_is_not_split_or_retried(
    monkeypatch,
):
    event = FakeEvent(forward_failure_limit=6)
    result = ParseResult(
        platform="test",
        image_urls=[f"base64://{index}" for index in range(7)],
    )

    messages = await collect_results(
        monkeypatch,
        result,
        event=event,
        forward_mode="always",
    )

    assert event.forward_attempt_sizes == [7]
    assert len(messages) == 1
    assert isinstance(messages[0][0], Plain)
    assert messages[0][0].text == "fake 合并转发发送失败: forward rejected"


@pytest.mark.asyncio
async def test_rejected_single_forward_node_is_not_retried(
    monkeypatch,
):
    event = FakeEvent(forward_failure_limit=0)

    messages = await collect_results(
        monkeypatch,
        ParseResult(platform="test", title="正文"),
        event=event,
        forward_mode="always",
    )

    assert event.forward_attempt_sizes == [1]
    assert len(messages) == 1
    assert isinstance(messages[0][0], Plain)
    assert messages[0][0].text == "fake 合并转发发送失败: forward rejected"


@pytest.mark.asyncio
async def test_aiocqhttp_forward_uses_remote_image_url_without_base64(
    monkeypatch,
    tmp_path,
):
    image_paths = [tmp_path / f"original-{index}.jpg" for index in range(7)]
    source_urls = [
        f"https://img.example/original-{index}.jpg" for index in range(7)
    ]
    for image_path in image_paths:
        image_path.write_bytes(b"large-original-image")
    result = ParseResult(
        platform="test",
        image_urls=[str(image_path) for image_path in image_paths],
        temporary_files=image_paths,
        image_source_urls={
            str(image_path.resolve()): source_url
            for image_path, source_url in zip(
                image_paths, source_urls, strict=True
            )
        },
    )
    bot = FakeBot()
    event = FakeEvent(
        bot=bot,
        raw_message={
            "group_id": 10001,
            "self_id": 20002,
            "sender": {"nickname": "测试用户"},
        },
    )

    messages = await collect_results(
        monkeypatch,
        result,
        event=event,
        forward_mode="always",
    )

    assert messages == []
    assert len(bot.actions) == 1
    action, params = bot.actions[0]
    assert action == "send_group_forward_msg"
    assert params["group_id"] == 10001
    assert params["self_id"] == 20002
    assert len(params["messages"]) == 7
    assert [
        node["data"]["content"][0]["data"]["file"]
        for node in params["messages"]
    ] == source_urls
    assert not any(
        node["data"]["content"][0]["data"]["file"].startswith("base64://")
        for node in params["messages"]
    )
    assert not any(image_path.exists() for image_path in image_paths)


@pytest.mark.asyncio
async def test_description_without_images_stays_in_plain_message(monkeypatch):
    result = ParseResult(platform="test", description="只有简介")

    messages = await collect_results(monkeypatch, result)

    assert len(messages) == 1
    assert len(messages[0]) == 1
    assert isinstance(messages[0][0], Plain)
    assert messages[0][0].text == "简介:\n只有简介"


@pytest.mark.asyncio
async def test_ordered_text_success_failure_success_preserves_component_order(
    monkeypatch,
):
    result = ParseResult(
        platform="test",
        title="摘要",
        ordered_contents=[
            OrderedContent("text", "正文一"),
            OrderedContent("image", "base64://1"),
            OrderedContent("image_error", "第 2 张图片获取失败"),
            OrderedContent("image", "base64://3"),
            OrderedContent("text", "正文二"),
        ],
    )

    messages = await collect_results(monkeypatch, result)

    nodes = messages[0][0].nodes
    assert [type(node.content[0]) for node in nodes] == [
        Plain,
        Image,
        Plain,
        Image,
        Plain,
    ]
    assert [
        component.text if isinstance(component, Plain) else component.file
        for node in nodes
        for component in node.content
    ] == [
        "摘要\n正文一",
        "base64://1",
        "第 2 张图片获取失败",
        "base64://3",
        "正文二",
    ]


@pytest.mark.asyncio
async def test_empty_summary_sends_only_nodes(monkeypatch):
    result = ParseResult(
        platform="test",
        image_urls=["base64://1", "base64://2", "base64://3"],
    )

    messages = await collect_results(monkeypatch, result)

    assert len(messages) == 1
    assert isinstance(messages[0][0], Nodes)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("sender", "sender_name", "sender_id", "expected_name", "expected_id"),
    [
        ({"card": "群名片", "nickname": "原始昵称"}, "公开昵称", 123, "群名片", "123"),
        ({"card": "", "nickname": "原始昵称"}, "公开昵称", 456, "公开昵称", "456"),
        ({}, "", 789, "789", "789"),
    ],
)
async def test_forward_nodes_use_sender_name_fallbacks(
    monkeypatch, sender, sender_name, sender_id, expected_name, expected_id
):
    result = ParseResult(
        platform="test",
        image_urls=["base64://1", "base64://2", "base64://3"],
    )
    event = FakeEvent(
        sender_id=sender_id,
        sender_name=sender_name,
        sender=sender,
    )

    messages = await collect_results(monkeypatch, result, event=event)

    for node in messages[0][0].nodes:
        assert node.name == expected_name
        assert node.uin == expected_id


@pytest.mark.asyncio
async def test_non_dict_raw_message_uses_public_sender_name(monkeypatch):
    result = ParseResult(
        platform="test",
        image_urls=["base64://1", "base64://2", "base64://3"],
    )
    event = FakeEvent(
        sender_id=123,
        sender_name=456,
        raw_message="not-onebot-json",
    )

    messages = await collect_results(monkeypatch, result, event=event)

    nodes = messages[0][0].nodes
    assert all(node.name == "456" and node.uin == "123" for node in nodes)


@pytest.mark.asyncio
@pytest.mark.parametrize("platform_name", ["telegram", "", "__raise__"])
async def test_unsupported_or_empty_platform_keeps_one_normal_chain(
    monkeypatch, platform_name
):
    result = ParseResult(
        platform="test",
        title="标题",
        image_urls=["base64://1", "base64://2", "base64://3"],
    )
    event = FakeEvent(platform_name=platform_name)

    messages = await collect_results(
        monkeypatch,
        result,
        event=event,
        forward_mode="always",
    )

    assert len(messages) == 1
    assert [type(component) for component in messages[0]] == [
        Image,
        Image,
        Image,
        Plain,
    ]
    assert not any(isinstance(component, Nodes) for component in messages[0])


@pytest.mark.asyncio
async def test_satori_supports_forward_nodes(monkeypatch):
    result = ParseResult(
        platform="test",
        title="标题",
        image_urls=["base64://1", "base64://2", "base64://3"],
    )

    messages = await collect_results(
        monkeypatch,
        result,
        event=FakeEvent(platform_name="satori"),
    )

    assert len(messages) == 1
    assert isinstance(messages[0][0], Nodes)


@pytest.mark.asyncio
async def test_always_mode_forwards_text_only_result(monkeypatch):
    messages = await collect_results(
        monkeypatch,
        ParseResult(platform="test", title="标题"),
        forward_mode="always",
    )

    assert len(messages) == 1
    assert isinstance(messages[0][0], Nodes)
    assert messages[0][0].nodes[0].content[0].text == "标题"


@pytest.mark.asyncio
async def test_never_mode_keeps_many_images_in_normal_chain(monkeypatch):
    result = ParseResult(
        platform="test",
        title="标题",
        image_urls=["base64://1", "base64://2", "base64://3"],
    )

    messages = await collect_results(monkeypatch, result, forward_mode="never")

    assert len(messages) == 1
    assert [type(component) for component in messages[0]] == [
        Image,
        Image,
        Image,
        Plain,
    ]
    assert not any(isinstance(component, Nodes) for component in messages[0])


@pytest.mark.asyncio
@pytest.mark.parametrize(("length", "should_forward"), [(200, False), (201, True)])
async def test_text_threshold_is_strictly_greater(monkeypatch, length, should_forward):
    messages = await collect_results(
        monkeypatch,
        ParseResult(platform="test", title="字" * length),
        forward_mode="threshold",
        forward_image_threshold=99,
        forward_text_threshold=200,
    )

    assert isinstance(messages[0][0], Nodes) is should_forward


@pytest.mark.asyncio
@pytest.mark.parametrize(("count", "should_forward"), [(2, False), (3, True)])
async def test_image_threshold_is_strictly_greater(monkeypatch, count, should_forward):
    result = ParseResult(
        platform="test",
        image_urls=[f"base64://{index}" for index in range(count)],
    )

    messages = await collect_results(
        monkeypatch,
        result,
        forward_mode="threshold",
        forward_image_threshold=2,
        forward_text_threshold=999,
    )

    assert isinstance(messages[0][0], Nodes) is should_forward


@pytest.mark.asyncio
async def test_text_threshold_counts_summary_and_ordered_body(monkeypatch):
    result = ParseResult(
        platform="test",
        title="题" * 100,
        ordered_contents=[OrderedContent("text", "文" * 101)],
    )

    messages = await collect_results(
        monkeypatch,
        result,
        forward_mode="threshold",
        forward_image_threshold=99,
        forward_text_threshold=200,
    )

    assert isinstance(messages[0][0], Nodes)


@pytest.mark.asyncio
async def test_invalid_forward_mode_falls_back_to_threshold(monkeypatch):
    result = ParseResult(
        platform="test",
        image_urls=["base64://1", "base64://2", "base64://3"],
    )

    messages = await collect_results(
        monkeypatch,
        result,
        forward_mode="unexpected",
    )

    assert isinstance(messages[0][0], Nodes)


@pytest.mark.asyncio
async def test_invalid_thresholds_fall_back_to_defaults(monkeypatch):
    result = ParseResult(
        platform="test",
        title="字" * 200,
        image_urls=["base64://1", "base64://2"],
    )

    messages = await collect_results(
        monkeypatch,
        result,
        forward_mode="threshold",
        forward_image_threshold="invalid",
        forward_text_threshold=None,
    )

    assert not any(isinstance(component, Nodes) for component in messages[0])


@pytest.mark.asyncio
async def test_negative_thresholds_are_treated_as_zero(monkeypatch):
    result = ParseResult(platform="test", image_urls=["base64://1"])

    messages = await collect_results(
        monkeypatch,
        result,
        forward_mode="threshold",
        forward_image_threshold=-1,
        forward_text_threshold=-1,
    )

    assert isinstance(messages[0][0], Nodes)


@pytest.mark.asyncio
async def test_threshold_forward_keeps_regular_video_as_separate_message(monkeypatch):
    result = ParseResult(
        platform="test",
        title="摘要",
        image_urls=["base64://1", "base64://2", "base64://3"],
        video_url="https://example.com/video.mp4",
    )
    plugin = make_plugin(result)
    monkeypatch.setattr(
        main, "extract_context", lambda event: SimpleNamespace(combined_text="url")
    )

    async def fake_probe(url):
        return VideoSizeInfo(size_bytes=1024)

    monkeypatch.setattr(plugin, "_probe_video_size", fake_probe)

    messages = await collect_plugin_results(plugin, FakeEvent())

    assert len(messages) == 2
    assert isinstance(messages[0][0], Nodes)
    assert not any(isinstance(node.content[0], Video) for node in messages[0][0].nodes)
    assert isinstance(messages[1][0], Video)
    assert messages[1][0].file == result.video_url


@pytest.mark.asyncio
async def test_threshold_forward_keeps_xiaoheihe_game_video_inside(monkeypatch):
    result = ParseResult(
        platform="xiaoheihe",
        title="游戏详情",
        description="游戏简介",
        image_urls=["base64://1", "base64://2", "base64://3"],
        video_url="https://example.com/game.mp4",
        keep_video_in_forward=True,
    )
    plugin = make_plugin(result)
    monkeypatch.setattr(
        main, "extract_context", lambda event: SimpleNamespace(combined_text="url")
    )

    async def fake_probe(url):
        return VideoSizeInfo(size_bytes=1024)

    monkeypatch.setattr(plugin, "_probe_video_size", fake_probe)

    messages = await collect_plugin_results(plugin, FakeEvent())

    assert len(messages) == 1
    assert isinstance(messages[0][0], Nodes)
    assert isinstance(messages[0][0].nodes[-1].content[0], Video)
    assert messages[0][0].nodes[-1].content[0].file == result.video_url


@pytest.mark.asyncio
async def test_always_forward_keeps_regular_video_inside(monkeypatch):
    result = ParseResult(
        platform="test",
        title="摘要",
        video_url="https://example.com/video.mp4",
    )
    plugin = make_plugin(result, forward_mode="always")
    monkeypatch.setattr(
        main, "extract_context", lambda event: SimpleNamespace(combined_text="url")
    )

    async def fake_probe(url):
        return VideoSizeInfo(size_bytes=1024)

    monkeypatch.setattr(plugin, "_probe_video_size", fake_probe)

    messages = await collect_plugin_results(plugin, FakeEvent())

    assert len(messages) == 1
    assert isinstance(messages[0][0], Nodes)
    assert isinstance(messages[0][0].nodes[-1].content[0], Video)


@pytest.mark.asyncio
async def test_forward_description_matches_plain_chain_format(monkeypatch):
    result = ParseResult(
        platform="test",
        title="标题",
        description="第一行\n第二行",
        image_urls=["base64://1", "base64://2", "base64://3"],
    )

    plain_messages = await collect_results(monkeypatch, result, forward_mode="never")
    forward_messages = await collect_results(monkeypatch, result)

    plain_chain = plain_messages[0]
    forward_chain = [node.content[0] for node in forward_messages[0][0].nodes]
    assert [type(component) for component in forward_chain] == [
        type(component) for component in plain_chain
    ]
    assert [
        component.text if isinstance(component, Plain) else component.file
        for component in forward_chain
    ] == [
        component.text if isinstance(component, Plain) else component.file
        for component in plain_chain
    ]
    assert forward_chain[-1].text == "标题\n简介:\n第一行\n第二行"


@pytest.mark.asyncio
async def test_non_forward_content_keeps_video_as_separate_message(monkeypatch):
    result = ParseResult(
        platform="test",
        title="summary",
        image_urls=["base64://1"],
        video_url="https://example.com/video.mp4",
    )
    plugin = make_plugin(result, forward_mode="never")
    monkeypatch.setattr(
        main, "extract_context", lambda event: SimpleNamespace(combined_text="url")
    )

    async def fake_probe(url):
        return VideoSizeInfo(size_bytes=1024)

    monkeypatch.setattr(plugin, "_probe_video_size", fake_probe)

    messages = await collect_plugin_results(plugin, FakeEvent())

    assert len(messages) == 2
    assert not isinstance(messages[0][0], Nodes)
    assert isinstance(messages[1][0], Video)


@pytest.mark.asyncio
async def test_audio_is_sent_after_track_summary(monkeypatch):
    result = ParseResult(
        platform="douyin",
        title="歌曲标题",
        audio_url="https://v3-luna.douyinvod.com/song.m4a",
    )

    messages = await collect_results(monkeypatch, result, forward_mode="never")

    assert len(messages) == 2
    assert isinstance(messages[0][0], Plain)
    assert messages[0][0].text == "歌曲标题"
    assert isinstance(messages[1][0], Record)
    assert messages[1][0].file == result.audio_url


@pytest.mark.asyncio
async def test_video_url_is_only_in_summary_when_direct_send_is_disabled(
    monkeypatch,
):
    result = ParseResult(
        platform="test",
        title="摘要",
        image_urls=["base64://1", "base64://2", "base64://3"],
        video_url="https://example.com/video.mp4",
    )
    plugin = make_plugin(result, send_video_by_url=False)
    monkeypatch.setattr(
        main, "extract_context", lambda event: SimpleNamespace(combined_text="url")
    )
    forwarded = []

    async def fake_forward(event, parsed_result, reason):
        forwarded.append((parsed_result, reason))

    monkeypatch.setattr(plugin, "_send_forward_links", fake_forward)

    messages = await collect_plugin_results(plugin, FakeEvent())

    assert len(messages) == 1
    nodes = messages[0][0].nodes
    plain_nodes = [
        node.content[0] for node in nodes if isinstance(node.content[0], Plain)
    ]
    assert (
        sum(
            "视频链接: https://example.com/video.mp4" in component.text
            for component in plain_nodes
        )
        == 1
    )
    assert len(forwarded) == 1


@pytest.mark.asyncio
async def test_probe_range_reads_headers_without_buffering_response_body(monkeypatch):
    class FailingStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            raise AssertionError("Range response body must not be read")
            yield b""

    def handler(request):
        if request.method == "HEAD":
            return httpx.Response(200, request=request)
        assert request.headers["Range"] == "bytes=0-0"
        return httpx.Response(
            206,
            headers={"Content-Length": "999999999"},
            content=FailingStream(),
            request=request,
        )

    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        main.httpx,
        "AsyncClient",
        lambda **kwargs: real_async_client(
            transport=httpx.MockTransport(handler), **kwargs
        ),
    )
    plugin = MultiParserPlugin.__new__(MultiParserPlugin)
    plugin.config = {"size_check_timeout_seconds": 5}

    size_info = await plugin._probe_video_size("https://example.com/video.mp4")

    assert size_info.size_bytes == 999999999


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("head_headers", "range_headers", "expected_size"),
    [
        ({"Content-Length": "123"}, {}, 123),
        ({}, {"Content-Range": "bytes 0-0/456"}, 456),
    ],
)
async def test_probe_preserves_head_and_content_range_header_parsing(
    monkeypatch, head_headers, range_headers, expected_size
):
    def handler(request):
        if request.method == "HEAD":
            return httpx.Response(200, headers=head_headers, request=request)
        return httpx.Response(
            206,
            headers=range_headers,
            content=b"ignored",
            request=request,
        )

    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        main.httpx,
        "AsyncClient",
        lambda **kwargs: real_async_client(
            transport=httpx.MockTransport(handler), **kwargs
        ),
    )
    plugin = MultiParserPlugin.__new__(MultiParserPlugin)
    plugin.config = {"size_check_timeout_seconds": 5}

    size_info = await plugin._probe_video_size("https://example.com/video.mp4")

    assert size_info.size_bytes == expected_size
