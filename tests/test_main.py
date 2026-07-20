from types import SimpleNamespace

import httpx
import pytest

from astrbot.api.message_components import Image, Node, Nodes, Plain, Video
from astrbot_multi_parser import main
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


class SavingConfig(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.save_calls = 0

    def save_config(self):
        self.save_calls += 1


class FakeEvent:
    def __init__(
        self,
        sender_id=123,
        sender_name="",
        sender=None,
        raw_message=None,
        platform_name="aiocqhttp",
    ):
        self.sender_id = sender_id
        self.sender_name = sender_name
        self.platform_name = platform_name
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
    return [item async for item in plugin.handle_parse(event or FakeEvent())]


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
async def test_exactly_three_images_repeat_summary_as_first_forward_node(
    monkeypatch,
):
    result = ParseResult(
        platform="test",
        title="标题",
        image_urls=["base64://1", "base64://2", "base64://3"],
    )

    messages = await collect_results(monkeypatch, result)

    assert len(messages) == 2
    assert len(messages[0]) == 1
    assert isinstance(messages[0][0], Plain)
    assert not any(isinstance(component, Image) for component in messages[0])
    assert len(messages[1]) == 1
    assert isinstance(messages[1][0], Nodes)
    nodes = messages[1][0].nodes
    assert len(nodes) == 4
    assert all(isinstance(node, Node) and len(node.content) == 1 for node in nodes)
    assert isinstance(nodes[0].content[0], Plain)
    assert nodes[0].content[0].text == messages[0][0].text == "标题"
    assert all(isinstance(node.content[0], Image) for node in nodes[1:])


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

    nodes = messages[1][0].nodes
    assert [type(node.content[0]) for node in nodes] == [
        Plain,
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
        "摘要",
        "正文一",
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

    messages = await collect_results(monkeypatch, result, event=event)

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

    assert len(messages) == 2
    assert isinstance(messages[1][0], Nodes)


@pytest.mark.asyncio
async def test_forward_images_are_followed_by_existing_video_flow(monkeypatch):
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

    messages = [item async for item in plugin.handle_parse(FakeEvent())]

    assert len(messages) == 3
    assert isinstance(messages[0][0], Plain)
    assert isinstance(messages[1][0], Nodes)
    assert isinstance(messages[2][0], Video)
    assert "视频链接" not in messages[0][0].text


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

    messages = [item async for item in plugin.handle_parse(FakeEvent())]

    assert len(messages) == 2
    assert "视频链接: https://example.com/video.mp4" in messages[0][0].text
    nodes = messages[1][0].nodes
    assert "视频链接: https://example.com/video.mp4" in nodes[0].content[0].text
    assert all(
        "视频链接" not in node.content[0].text
        for node in nodes[1:]
        if isinstance(node.content[0], Plain)
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
