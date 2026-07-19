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
from astrbot_multi_parser.platforms.zhihu.handlers import (
    parse_answer_payload,
    parse_article_payload,
    parse_pin_payload,
    parse_question_payload,
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


def test_answer_payload_builds_author_stats_and_ordered_body():
    result = parse_answer_payload(
        {
            "question": {"title": "问题标题"},
            "author": {"name": "答主"},
            "content": (
                "<p>回答正文</p>"
                '<img src="https://picx.zhimg.com/answer.jpg">'
                '<video src="https://video.zhihu.com/answer.mp4"></video>'
            ),
            "voteupCount": 12,
            "commentCount": 3,
            "favoriteCount": 2,
        }
    )

    assert result.title == "问题标题"
    assert result.author == "答主"
    assert result.extra_lines == ["赞同 12 | 评论 3 | 收藏 2"]
    assert [(item.kind, item.value) for item in result.ordered_contents] == [
        ("text", "回答正文"),
        ("image", "https://picx.zhimg.com/answer.jpg"),
    ]
    assert result.video_url == "https://video.zhihu.com/answer.mp4"


def test_question_payload_appends_default_first_answer():
    result = parse_question_payload(
        {
            "title": "问题标题",
            "detail": "<p>问题描述</p>",
            "author": {"name": "提问者"},
            "answerCount": 5,
            "followerCount": 12000,
            "visitCount": 100000000,
        },
        {
            "author": {"name": "首答作者"},
            "content": "<p>首条回答</p>",
        },
    )

    assert result.title == "问题标题"
    assert result.author == "首答作者"
    assert result.extra_lines == ["回答 5 | 关注 1.2万 | 浏览 1亿"]
    assert [(item.kind, item.value) for item in result.ordered_contents] == [
        ("text", "问题描述"),
        ("text", "默认排序首条回答 @首答作者"),
        ("text", "首条回答"),
    ]


def test_article_payload_uses_article_title_and_multiple_video_policy():
    result = parse_article_payload(
        {
            "title": "专栏标题",
            "author": {"name": "文章作者"},
            "content": (
                "<p>文章正文</p>"
                '<video src="https://video.zhihu.com/first.mp4"></video>'
                '<video src="https://video.zhihu.com/second.mp4"></video>'
            ),
            "voteupCount": 20000,
            "commentCount": 4,
        }
    )

    assert result.title == "专栏标题"
    assert result.author == "文章作者"
    assert result.video_url == "https://video.zhihu.com/first.mp4"
    assert result.ordered_contents[-1] == OrderedContent(
        kind="text",
        value="视频链接: https://video.zhihu.com/second.mp4",
    )
    assert result.extra_lines == ["赞同 2万 | 评论 4"]


def test_pin_payload_handles_structured_text_image_and_video():
    result = parse_pin_payload(
        {
            "author": {"name": "想法作者"},
            "content": [
                {"type": "text", "content": "想法正文"},
                {
                    "type": "image",
                    "url": "https://pic1.zhimg.com/pin.jpg",
                },
                {
                    "type": "video",
                    "video": {
                        "playlist": {
                            "hd": {"playUrl": "https://video.zhihu.com/pin.mp4"}
                        }
                    },
                },
            ],
            "voteup_count": 8,
            "comment_count": 1,
        }
    )

    assert result.title == "知乎想法"
    assert result.author == "想法作者"
    assert result.ordered_contents == [
        OrderedContent(kind="text", value="想法正文"),
        OrderedContent(kind="image", value="https://pic1.zhimg.com/pin.jpg"),
    ]
    assert result.video_url == "https://video.zhihu.com/pin.mp4"
    assert result.extra_lines == ["赞同 8 | 评论 1"]


@pytest.mark.parametrize(
    ("handler", "payload", "message"),
    [
        (parse_answer_payload, {}, "知乎回答数据为空"),
        (parse_article_payload, {}, "知乎文章数据为空"),
        (parse_pin_payload, {}, "知乎想法数据为空"),
    ],
)
def test_handlers_reject_empty_payloads(handler, payload, message):
    with pytest.raises(ValueError, match=message):
        handler(payload)
