from astrbot_multi_parser.services.configuration import build_parsers


def test_registry_order_is_stable():
    assert list(build_parsers({})) == [
        "bilibili",
        "douyin",
        "redbook",
        "tieba",
        "weibo",
        "wechat",
        "xiaoheihe",
        "zhihu",
    ]
