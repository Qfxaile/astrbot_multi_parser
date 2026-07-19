import pytest

from astrbot_multi_parser.models import OrderedContent, ParseContext
from astrbot_multi_parser.platforms.zhihu.common import (
    merge_unique_urls,
    normalize_media_url,
    normalize_text,
)
from astrbot_multi_parser.platforms.zhihu.content import (
    extract_html_video_urls,
    parse_html_body,
)


def test_normalize_text_decodes_entities_and_compacts_whitespace():
    assert normalize_text("  第一段&nbsp; 内容\r\n\r\n\r\n第二段  ", keep_newlines=True) == (
        "第一段 内容\n\n第二段"
    )


@pytest.mark.parametrize(
    ("value", "page_url", "expected"),
    [
        ("//picx.zhimg.com/a.jpg", None, "https://picx.zhimg.com/a.jpg"),
        ("/video/a.mp4", "https://www.zhihu.com/question/1", "https://www.zhihu.com/video/a.mp4"),
        ("javascript:alert(1)", None, ""),
        ("data:image/png;base64,AAAA", None, ""),
    ],
)
def test_normalize_media_url_accepts_only_http_urls(value, page_url, expected):
    assert normalize_media_url(value, page_url) == expected


def test_merge_unique_urls_ignores_query_for_same_media():
    assert merge_unique_urls(
        ["https://picx.zhimg.com/a.jpg?source=1"],
        [
            "http://picx.zhimg.com/a.jpg?source=2",
            "https://picx.zhimg.com/b.jpg",
        ],
    ) == [
        "https://picx.zhimg.com/a.jpg?source=1",
        "https://picx.zhimg.com/b.jpg",
    ]


def test_html_body_keeps_text_and_image_order():
    body = (
        "<p>第一段</p>"
        '<figure><img data-original="//picx.zhimg.com/a.jpg"></figure>'
        "<p>第二段<br>下一行</p>"
    )

    blocks = parse_html_body(body)

    assert blocks == [
        OrderedContent(kind="text", value="第一段"),
        OrderedContent(kind="image", value="https://picx.zhimg.com/a.jpg"),
        OrderedContent(kind="text", value="第二段"),
        OrderedContent(kind="text", value="下一行"),
    ]


def test_html_body_filters_hidden_nodes_and_duplicate_images():
    body = (
        "<style>隐藏样式</style><script>隐藏脚本</script>"
        "<p>正文</p>"
        '<img src="https://pic1.zhimg.com/a.jpg?x=1">'
        '<img data-original="https://pic1.zhimg.com/a.jpg?x=2">'
    )

    blocks = parse_html_body(body)

    assert blocks == [
        OrderedContent(kind="text", value="正文"),
        OrderedContent(kind="image", value="https://pic1.zhimg.com/a.jpg?x=1"),
    ]


def test_extract_html_video_urls_uses_source_and_link_candidates():
    body = (
        '<video src="https://video.zhihu.com/a.mp4"></video>'
        '<a data-video-id="2" href="https://video.zhihu.com/b.m3u8">视频</a>'
        '<source src="https://video.zhihu.com/a.mp4?duplicate=1">'
    )

    assert extract_html_video_urls(body) == [
        "https://video.zhihu.com/a.mp4",
        "https://video.zhihu.com/b.m3u8",
    ]


@pytest.mark.asyncio
async def test_placeholder_parser_still_matches_question_url():
    from astrbot_multi_parser.platforms import ZhihuParser

    assert await ZhihuParser({}).match(
        ParseContext(text="https://www.zhihu.com/question/123")
    )
