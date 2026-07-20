from astrbot_multi_parser.core.http import (
    build_cookies,
    parse_cookie_header,
    request_timeout,
)


def test_parse_cookie_header_keeps_values_containing_equals():
    assert parse_cookie_header("a=1; invalid; b=two=2; =ignored") == [
        ("a", "1"),
        ("b", "two=2"),
    ]


def test_build_cookies_scopes_each_pair_to_all_domains():
    cookies = build_cookies("a=1; b=2", (".a.test", ".b.test"))

    scoped = {(item.name, item.value, item.domain) for item in cookies.jar}
    assert scoped == {
        ("a", "1", ".a.test"),
        ("a", "1", ".b.test"),
        ("b", "2", ".a.test"),
        ("b", "2", ".b.test"),
    }


def test_request_timeout_accepts_numeric_config():
    assert request_timeout({"request_timeout_seconds": "12.5"}) == 12.5
    assert request_timeout({}) == 30.0
