import base64
import json
import re
from types import SimpleNamespace

import httpx
import pytest

from astrbot_multi_parser.models import ParseContext
from astrbot_multi_parser.platforms import xiaoheihe
from astrbot_multi_parser.platforms.xiaoheihe import XiaoheiheParser


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "https://www.xiaoheihe.cn/app/bbs/link/abc123",
        "https://api.xiaoheihe.cn/v3/bbs/app/api/web/share?foo=1&link_id=abc123",
        "https://www.xiaoheihe.cn/app/topic/game/pc/730",
        "https://api.xiaoheihe.cn/game/share_game_detail?appid=730&game_type=pc",
    ],
)
async def test_matches_supported_xiaoheihe_urls(url):
    assert await XiaoheiheParser({}).match(ParseContext(text=url))


@pytest.mark.asyncio
async def test_rejects_lookalike_xiaoheihe_urls():
    assert not await XiaoheiheParser({}).match(
        ParseContext(text="https://xiaoheihe.cn.evil.example/app/bbs/link/abc123")
    )


def test_extracts_token_from_cookie_header():
    parser = XiaoheiheParser(
        {"xiaoheihe_cookies": "foo=bar; x_xhh_tokenid=Bdevice123"}
    )

    assert parser._extract_xhh_tokenid_from_cookies() == "Bdevice123"


def test_signing_algorithm_matches_reference_golden_value(monkeypatch):
    parser = XiaoheiheParser({})

    assert parser._ov(
        "/bbs/app/link/tree",
        1700000001,
        "ABCDEF0123456789ABCDEF0123456789",
    ) == "V2V1Z67"

    monkeypatch.setattr(xiaoheihe.time, "time", lambda: 1700000000)
    monkeypatch.setattr(xiaoheihe.random, "random", lambda: 0.5)
    result = parser._sign_path("/bbs/app/link/tree")

    assert result["_time"] == 1700000000
    assert re.fullmatch(r"[0-9A-F]{32}", str(result["nonce"]))
    assert result["hkey"] == parser._ov(
        "/bbs/app/link/tree", 1700000001, str(result["nonce"])
    )


def test_post_payload_keeps_text_and_images_in_source_order():
    payload = {
        "link": {
            "title": "帖子标题",
            "user": {"username": "盒友"},
            "text": json.dumps(
                [
                    {"type": "text", "text": "<p>第一段</p>"},
                    {
                        "type": "img",
                        "url": "https://imgheybox.max-c.com/bbs/a.jpg?token=1",
                    },
                    {
                        "type": "text",
                        "text": (
                            '<p>第二段<img data-original="https://imgheybox1.max-c.com/bbs/b.jpg?token=2">'
                            "<br>第三段</p>"
                        ),
                    },
                    {
                        "type": "img",
                        "url": "https://imgheybox1.max-c.com/bbs/a.jpg?token=duplicate",
                    },
                ]
            ),
            "has_video": True,
            "video_url": "https://video.max-c.com/bbs/post.mp4",
        }
    }

    result = XiaoheiheParser({})._parse_post_payload(payload)

    assert result.title == "帖子标题"
    assert result.author == "盒友"
    assert result.video_url == "https://video.max-c.com/bbs/post.mp4"
    assert [(item.kind, item.value) for item in result.ordered_contents] == [
        ("text", "第一段"),
        ("image", "https://imgheybox.max-c.com/bbs/a.jpg?token=1"),
        ("text", "第二段"),
        ("image", "https://imgheybox.max-c.com/bbs/b.jpg?token=2"),
        ("text", "第三段"),
    ]


def test_post_payload_rejects_missing_link():
    with pytest.raises(ValueError, match="缺少 link 节点"):
        XiaoheiheParser({})._parse_post_payload({"status": "ok"})


def install_mock_client(monkeypatch, handler):
    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        xiaoheihe,
        "httpx",
        SimpleNamespace(
            AsyncClient=lambda **kwargs: real_async_client(
                transport=httpx.MockTransport(handler), **kwargs
            )
        ),
        raising=False,
    )


@pytest.mark.asyncio
async def test_parse_post_requests_signed_tree_and_materializes_images(monkeypatch):
    image_bytes = b"post-image"
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "api.xiaoheihe.cn":
            assert request.url.path == "/bbs/app/link/tree"
            assert request.url.params["link_id"] == "abc123"
            assert request.url.params["hkey"]
            assert request.headers.get("cookie") == "x_xhh_tokenid=Bdevice123"
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "result": {
                        "link": {
                            "title": "接口帖子",
                            "user": {"username": "接口作者"},
                            "text": json.dumps(
                                [
                                    {
                                        "type": "img",
                                        "url": "https://imgheybox.max-c.com/bbs/a.jpg",
                                    }
                                ]
                            ),
                        }
                    },
                },
                request=request,
            )
        assert request.url.host == "imgheybox.max-c.com"
        return httpx.Response(200, content=image_bytes, request=request)

    install_mock_client(monkeypatch, handler)
    parser = XiaoheiheParser(
        {"xiaoheihe_cookies": "x_xhh_tokenid=Bdevice123"}
    )

    result = await parser.parse(
        ParseContext(text="https://www.xiaoheihe.cn/app/bbs/link/abc123")
    )

    assert result.title == "接口帖子"
    assert result.author == "接口作者"
    assert result.ordered_contents[0].value == (
        f"base64://{base64.b64encode(image_bytes).decode()}"
    )
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_parse_post_reports_api_error_without_token_leak(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"status": "error", "msg": "denied"},
            request=request,
        )

    install_mock_client(monkeypatch, handler)
    parser = XiaoheiheParser(
        {"xiaoheihe_cookies": "x_xhh_tokenid=Bsecret"}
    )

    with pytest.raises(ValueError, match="link/tree 请求失败") as exc_info:
        await parser.parse(
            ParseContext(text="https://www.xiaoheihe.cn/app/bbs/link/abc123")
        )

    assert "Bsecret" not in str(exc_info.value)
