import pytest

from astrbot_multi_parser.models import ParseContext
from astrbot_multi_parser.platforms.weibo import WeiboParser


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "https://weibo.com/7207262816/P5kWdcfDe",
        "https://m.weibo.cn/status/5234367615996775",
        "https://m.weibo.cn/detail/4976424138313924",
        "https://weibo.com/tv/show/1034:5007449447661594?mid=5007452630158934",
        "https://video.weibo.com/show?fid=1034:5145615399845897",
        "https://mapp.api.weibo.cn/fx/233911ddcc6bffea835a55e725fb0ebc.html",
        "https://weibo.com/ttarticle/p/show?id=2309404962180771742222",
        "https://card.weibo.com/article/m/show/id/2309404962180771742222",
    ],
)
async def test_matches_supported_weibo_urls(url):
    assert await WeiboParser({}).match(ParseContext(text=url))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "https://evilweibo.com/7207262816/P5kWdcfDe",
        "https://weibo.com.evil.example/7207262816/P5kWdcfDe",
        "https://example.com/?next=https://weibo.com.evil/1/abc",
    ],
)
async def test_rejects_lookalike_weibo_hosts(url):
    assert not await WeiboParser({}).match(ParseContext(text=url))


def test_mid_to_bid_uses_weibo_base62_chunks():
    parser = WeiboParser({})

    assert parser._base62_encode(0) == "0"
    assert parser._base62_encode(61) == "Z"
    assert parser._base62_encode(62) == "10"
    assert parser._mid_to_bid("3501756485200075") == "z0JH2lOMb"


def test_status_payload_keeps_text_images_and_repost_order():
    payload = {
        "user": {
            "id": 123,
            "screen_name": "微博作者",
            "profile_image_url": "https://tvax1.sinaimg.cn/avatar.jpg",
        },
        "bid": "P5kWdcfDe",
        "text": "正文<br />第二行 &amp; 更多",
        "status_title": "微博标题",
        "pics": [
            {
                "url": "https://wx1.sinaimg.cn/thumb/a.jpg",
                "large": {"url": "https://wx1.sinaimg.cn/large/a.jpg"},
            }
        ],
        "page_info": {
            "title": "视频标题",
            "page_pic": {"url": "https://wx1.sinaimg.cn/large/cover.jpg"},
            "urls": {
                "mp4_ld_mp4": "//f.video.weibocdn.com/low.mp4",
                "mp4_hd_mp4": "https://f.video.weibocdn.com/high.mp4",
                "mp4_720p_mp4": "https://f.video.weibocdn.com/720.mp4",
            },
        },
        "retweeted_status": {
            "user": {"id": 456, "screen_name": "原作者"},
            "bid": "AbCdEf",
            "text": "<p>原微博</p>",
            "pics": [
                {"large": {"url": "https://wx2.sinaimg.cn/large/b.jpg"}}
            ],
        },
    }

    result = WeiboParser({})._parse_status_payload(payload)

    assert result.title == "视频标题"
    assert result.author == "微博作者"
    assert result.description == ""
    assert result.video_url == "https://f.video.weibocdn.com/720.mp4"
    assert result.cover_urls == ["https://wx1.sinaimg.cn/large/cover.jpg"]
    assert [(item.kind, item.value) for item in result.ordered_contents] == [
        ("text", "正文\n第二行 & 更多"),
        ("image", "https://wx1.sinaimg.cn/large/a.jpg"),
        ("text", "转发自 @原作者\n原微博"),
        ("image", "https://wx2.sinaimg.cn/large/b.jpg"),
    ]


def test_status_payload_uses_repost_video_when_original_has_none():
    payload = {
        "user": {"screen_name": "转发者"},
        "text": "转发微博",
        "retweeted_status": {
            "user": {"screen_name": "视频作者"},
            "text": "原视频",
            "page_info": {
                "page_pic": {"url": "//wx1.sinaimg.cn/cover.jpg"},
                "urls": {"mp4_hd_mp4": "//f.video.weibocdn.com/repost.mp4"},
            },
        },
    }

    result = WeiboParser({})._parse_status_payload(payload)

    assert result.video_url == "https://f.video.weibocdn.com/repost.mp4"
    assert result.cover_urls == ["https://wx1.sinaimg.cn/cover.jpg"]


def test_status_payload_rejects_missing_user_data():
    with pytest.raises(ValueError, match="微博作者数据为空"):
        WeiboParser({})._parse_status_payload({"text": "没有作者"})
