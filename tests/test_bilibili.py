import base64

import httpx
import pytest

from astrbot_multi_parser.models import ParseContext, ParseResult
from astrbot_multi_parser.platforms import bilibili


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://i0.hdslb.com/bfs/new_dyn/image.jpg@672w_378h_1c.webp",
            "https://i0.hdslb.com/bfs/new_dyn/image.jpg",
        ),
        (
            "//i0.hdslb.com/bfs/article/image.png@!web-article-pic.avif",
            "https://i0.hdslb.com/bfs/article/image.png",
        ),
        (
            "https://img.example/user@2x/image.jpg",
            "https://img.example/user@2x/image.jpg",
        ),
        (
            "https://evilhdslb.com/image.jpg@672w.webp",
            "https://evilhdslb.com/image.jpg@672w.webp",
        ),
        (
            "https://hdslb.com.evil/image.jpg@672w.webp",
            "https://hdslb.com.evil/image.jpg@672w.webp",
        ),
        (
            "https://user:pass@i0.hdslb.com:443/image.jpg@672w.webp?token=a@b#part@2",
            "https://user:pass@i0.hdslb.com:443/image.jpg?token=a@b#part@2",
        ),
        (
            "//user:pass@i0.hdslb.com:443/image.jpg@672w.webp?token=a@b#part@2",
            "https://user:pass@i0.hdslb.com:443/image.jpg?token=a@b#part@2",
        ),
        (
            "https://[invalid/image.jpg@672w.webp",
            "https://[invalid/image.jpg@672w.webp",
        ),
        (
            "https://i0.hdslb.com:bad/image.jpg@672w.webp",
            "https://i0.hdslb.com:bad/image.jpg@672w.webp",
        ),
        (
            "https://i0.hdslb.com:70000/image.jpg@672w.webp",
            "https://i0.hdslb.com:70000/image.jpg@672w.webp",
        ),
        (
            "https://i0.hdslb.com:8443/image.jpg@672w.webp",
            "https://i0.hdslb.com:8443/image.jpg",
        ),
        (
            "https://i0.hdslb.com/user@2x/image.jpg",
            "https://i0.hdslb.com/user@2x/image.jpg",
        ),
        (
            "https://i0.hdslb.com/user@2x/image.jpg@1048w_!web-dynamic.avif",
            "https://i0.hdslb.com/user@2x/image.jpg",
        ),
        (
            "https://i0.hdslb.com/image.jpg@not-a-transform",
            "https://i0.hdslb.com/image.jpg@not-a-transform",
        ),
    ],
)
def test_original_image_url_only_removes_hdslb_transform(url, expected):
    assert bilibili._original_image_url(url) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "https://t.bilibili.com/123",
        "https://www.bilibili.com/dynamic/123",
        "https://www.bilibili.com/opus/456",
        "https://www.bilibili.com/read/cv789",
    ],
)
async def test_matches_bilibili_graphic_urls(url):
    parser = bilibili.BilibiliParser({"request_timeout_seconds": 30})

    assert await parser.match(ParseContext(text=url))


def test_dynamic_payload_extracts_text_and_images_in_order():
    payload = {
        "code": 0,
        "data": {
            "item": {
                "modules": {
                    "module_author": {"name": "动态作者"},
                    "module_dynamic": {
                        "desc": {"text": "动态正文"},
                        "major": {
                            "type": "MAJOR_TYPE_OPUS",
                            "opus": {
                                "title": "动态标题",
                                "pics": [
                                    {
                                        "url": "https://i0.hdslb.com/dynamic.jpg@672w.webp"
                                    }
                                ],
                            },
                        },
                    },
                }
            }
        },
    }

    result = bilibili.BilibiliParser({})._parse_dynamic_payload(payload)

    assert result.title == "动态标题"
    assert result.author == "动态作者"
    assert [(item.kind, item.value) for item in result.ordered_contents] == [
        ("text", "动态正文"),
        ("image", "https://i0.hdslb.com/dynamic.jpg"),
    ]


def test_dynamic_archive_uses_original_cover_url():
    payload = {
        "code": 0,
        "data": {
            "item": {
                "modules": {
                    "module_author": {"name": "动态作者"},
                    "module_dynamic": {
                        "major": {
                            "type": "MAJOR_TYPE_ARCHIVE",
                            "archive": {
                                "title": "视频标题",
                                "cover": "//i0.hdslb.com/archive.jpg@672w.webp",
                            },
                        }
                    },
                }
            }
        },
    }

    result = bilibili.BilibiliParser({})._parse_dynamic_payload(payload)

    assert [(item.kind, item.value) for item in result.ordered_contents] == [
        ("image", "https://i0.hdslb.com/archive.jpg")
    ]


def test_opus_payload_keeps_paragraph_order():
    payload = {
        "code": 0,
        "data": {
            "item": {
                "basic": {"title": "图文标题"},
                "modules": [
                    {
                        "module_type": "MODULE_TYPE_AUTHOR",
                        "module_author": {"name": "图文作者"},
                    },
                    {
                        "module_type": "MODULE_TYPE_CONTENT",
                        "module_content": {
                            "paragraphs": [
                                {
                                    "text": {
                                        "nodes": [
                                            {
                                                "type": "TEXT_NODE_TYPE_WORD",
                                                "word": {"words": "第一段"},
                                            }
                                        ]
                                    }
                                },
                                {
                                    "pic": {
                                        "pics": [
                                            {
                                                "url": "//i0.hdslb.com/opus.jpg@!web-comment-note.avif"
                                            }
                                        ]
                                    }
                                },
                                {
                                    "text": {
                                        "nodes": [
                                            {
                                                "type": "TEXT_NODE_TYPE_RICH",
                                                "rich": {"text": "第二段"},
                                            }
                                        ]
                                    }
                                },
                            ]
                        },
                    },
                ],
            }
        },
    }

    result = bilibili.BilibiliParser({})._parse_opus_payload(payload)

    assert result.title == "图文标题"
    assert result.author == "图文作者"
    assert [(item.kind, item.value) for item in result.ordered_contents] == [
        ("text", "第一段"),
        ("image", "https://i0.hdslb.com/opus.jpg"),
        ("text", "第二段"),
    ]


def test_article_html_keeps_visible_text_and_image_order():
    html = """
    <html>
      <head>
        <meta property="og:title" content="专栏标题">
        <meta name="author" content="专栏作者">
      </head>
      <body>
        <div class="article-holder">
          <p>第一段</p>
          <figure><img data-src="//i0.hdslb.com/article.jpg@!web-article-pic.avif"></figure>
          <p>第二段</p>
        </div>
      </body>
    </html>
    """

    result = bilibili.BilibiliParser({})._parse_article_html(html)

    assert result.title == "专栏标题"
    assert result.author == "专栏作者"
    assert [(item.kind, item.value) for item in result.ordered_contents] == [
        ("text", "第一段"),
        ("image", "https://i0.hdslb.com/article.jpg"),
        ("text", "第二段"),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("page_url", "api_path", "payload", "expected_referer"),
    [
        (
            "https://t.bilibili.com/123",
            "/x/polymer/web-dynamic/v1/detail",
            {
                "code": 0,
                "data": {
                    "item": {
                        "modules": {
                            "module_author": {"name": "动态作者"},
                            "module_dynamic": {
                                "major": {
                                    "type": "MAJOR_TYPE_OPUS",
                                    "opus": {
                                        "pics": [
                                            {
                                                "url": "https://i0.hdslb.com/dynamic.jpg@672w.webp"
                                            }
                                        ]
                                    },
                                }
                            },
                        }
                    }
                },
            },
            "https://www.bilibili.com",
        ),
        (
            "https://www.bilibili.com/opus/456",
            "/x/polymer/web-dynamic/v1/opus/detail",
            {
                "code": 0,
                "data": {
                    "item": {
                        "basic": {"title": "图文标题"},
                        "modules": [
                            {
                                "module_content": {
                                    "paragraphs": [
                                        {
                                            "pic": {
                                                "pics": [
                                                    {
                                                        "url": "https://i0.hdslb.com/opus.jpg@!web-comment-note.avif"
                                                    }
                                                ]
                                            }
                                        }
                                    ]
                                }
                            }
                        ],
                    }
                },
            },
            "https://www.bilibili.com/opus/456",
        ),
    ],
)
async def test_dynamic_and_opus_materialize_original_images(
    monkeypatch, page_url, api_path, payload, expected_referer
):
    image_request = None
    client_kwargs = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal image_request
        if request.url.path == api_path:
            return httpx.Response(200, json=payload, request=request)
        image_request = request
        return httpx.Response(200, content=b"graphic-image", request=request)

    async_client = httpx.AsyncClient

    def create_client(**kwargs):
        nonlocal client_kwargs
        client_kwargs = kwargs
        return async_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(bilibili.httpx, "AsyncClient", create_client)

    result = await bilibili.BilibiliParser({}).parse(ParseContext(text=page_url))

    assert [(item.kind, item.value) for item in result.ordered_contents] == [
        ("image", f"base64://{base64.b64encode(b'graphic-image').decode()}")
    ]
    assert image_request is not None
    assert str(image_request.url) in {
        "https://i0.hdslb.com/dynamic.jpg",
        "https://i0.hdslb.com/opus.jpg",
    }
    assert image_request.headers["Referer"] == expected_referer
    assert client_kwargs is not None
    assert client_kwargs["headers"]["Referer"] == expected_referer
    assert "Mozilla/5.0" in client_kwargs["headers"]["User-Agent"]


@pytest.mark.asyncio
async def test_article_materializes_original_image_and_preserves_failed_slot(monkeypatch):
    article_url = "https://www.bilibili.com/read/cv789"
    html = """
    <html><head><meta property="og:title" content="专栏标题"></head>
    <body><div class="article-holder">
      <p>第一段</p>
      <img src="//i0.hdslb.com/failed.jpg@!web-article-pic.avif">
      <p>第二段</p>
      <img src="//i0.hdslb.com/working.jpg@672w.webp">
    </div></body></html>
    """
    image_requests = []
    client_kwargs = None

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/read/cv789":
            return httpx.Response(200, text=html, request=request)
        image_requests.append(request)
        if request.url.path.endswith("failed.jpg"):
            return httpx.Response(403, request=request)
        return httpx.Response(200, content=b"article-image", request=request)

    async_client = httpx.AsyncClient

    def create_client(**kwargs):
        nonlocal client_kwargs
        client_kwargs = kwargs
        return async_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(bilibili.httpx, "AsyncClient", create_client)

    result = await bilibili.BilibiliParser({}).parse(ParseContext(text=article_url))

    assert [(item.kind, item.value) for item in result.ordered_contents] == [
        ("text", "第一段"),
        ("image_error", "第 1 张图片获取失败：HTTP 403"),
        ("text", "第二段"),
        ("image", f"base64://{base64.b64encode(b'article-image').decode()}"),
    ]
    assert [str(request.url) for request in image_requests] == [
        "https://i0.hdslb.com/failed.jpg",
        "https://i0.hdslb.com/working.jpg",
    ]
    assert all(request.headers["Referer"] == article_url for request in image_requests)
    assert client_kwargs is not None
    assert client_kwargs["headers"]["Referer"] == article_url
    assert "Mozilla/5.0" in client_kwargs["headers"]["User-Agent"]


@pytest.mark.asyncio
async def test_video_materializes_original_cover(monkeypatch):
    parser = bilibili.BilibiliParser({})

    async def get_video_info(video_id):
        return {
            "title": "视频标题",
            "author": "视频作者",
            "desc": "视频简介",
            "cid": "1",
            "pic": "https://i0.hdslb.com/video.jpg@672w.webp",
        }

    async def get_play_url(cid, video_id):
        return "https://video.example/play.mp4"

    image_request = None
    client_kwargs = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal image_request
        image_request = request
        return httpx.Response(200, content=b"video-cover", request=request)

    async_client = httpx.AsyncClient

    def create_client(**kwargs):
        nonlocal client_kwargs
        client_kwargs = kwargs
        return async_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(parser, "_get_video_info", get_video_info)
    monkeypatch.setattr(parser, "_get_play_url", get_play_url)
    monkeypatch.setattr(bilibili.httpx, "AsyncClient", create_client)

    result = await parser.parse(ParseContext(text="BV1xx411c7mD"))

    assert result.cover_urls == [
        f"base64://{base64.b64encode(b'video-cover').decode()}"
    ]
    assert result.video_url == "https://video.example/play.mp4"
    assert image_request is not None
    assert str(image_request.url) == "https://i0.hdslb.com/video.jpg"
    assert image_request.headers["Referer"] == "https://www.bilibili.com"
    assert client_kwargs is not None
    assert client_kwargs["headers"]["Referer"] == "https://www.bilibili.com"
    assert "Mozilla/5.0" in client_kwargs["headers"]["User-Agent"]


@pytest.mark.asyncio
async def test_bilibili_rejects_external_image_without_request():
    requested_urls = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(200, content=b"unexpected", request=request)

    parser = bilibili.BilibiliParser({})
    result = ParseResult(
        platform="bilibili", image_urls=["https://img.example/external.jpg"]
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await parser.materialize_images(result, client, "https://www.bilibili.com")

    assert requested_urls == []
    assert result.image_urls == [""]
    assert result.image_errors == {0: "第 1 张图片获取失败：InvalidURL"}
