import json
from pathlib import Path

PLATFORMS = ("bilibili", "douyin", "redbook", "weibo", "xiaoheihe", "zhihu")
COOKIE_KEYS = (
    "douyin_cookies",
    "redbook_cookies",
    "weibo_cookies",
    "xiaoheihe_cookies",
    "zhihu_cookies",
)


def test_schema_uses_platform_switches_and_keeps_legacy_list_hidden():
    schema_path = Path(__file__).parents[1] / "_conf_schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    assert "douyin_api_url" not in schema
    assert "redbook_api_url" not in schema
    platform_switches = schema["platform_switches"]
    assert platform_switches["type"] == "object"
    assert tuple(platform_switches["items"]) == PLATFORMS
    for platform in PLATFORMS:
        assert platform_switches["items"][platform]["type"] == "bool"
        assert platform_switches["items"][platform]["default"] is True

    assert schema["enabled_platforms"]["type"] == "list"
    assert schema["enabled_platforms"]["default"] == list(PLATFORMS)
    assert schema["enabled_platforms"]["invisible"] is True
    assert schema["platform_switches_migrated"] == {
        "description": "平台开关迁移状态",
        "type": "bool",
        "default": False,
        "invisible": True,
    }

    for cookie_key in COOKIE_KEYS:
        cookie_config = schema[cookie_key]
        assert cookie_config["type"] == "text"
        assert cookie_config["default"] == ""
    assert tuple(schema)[-len(COOKIE_KEYS) :] == COOKIE_KEYS
    assert schema["max_video_size_mb"]["default"] == 50


def test_video_send_decision_defaults_limit_to_50_mb():
    from astrbot_multi_parser.main import MultiParserPlugin, VideoSizeInfo

    plugin = MultiParserPlugin.__new__(MultiParserPlugin)
    plugin.config = {}

    should_send, reason = plugin._video_send_decision(
        VideoSizeInfo(size_bytes=51 * 1024 * 1024)
    )

    assert should_send is False
    assert "超过限制 50.00 MB" in reason
