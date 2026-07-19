import json
from pathlib import Path

from astrbot_multi_parser.main import MultiParserPlugin, VideoSizeInfo


def test_schema_uses_optional_platform_cookies():
    schema_path = Path(__file__).parents[1] / "_conf_schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    assert "douyin_api_url" not in schema
    assert "redbook_api_url" not in schema
    assert schema["douyin_cookies"]["type"] == "text"
    assert schema["douyin_cookies"]["default"] == ""
    assert schema["redbook_cookies"]["type"] == "text"
    assert schema["redbook_cookies"]["default"] == ""
    assert schema["max_video_size_mb"]["default"] == 50


def test_video_send_decision_defaults_limit_to_50_mb():
    plugin = MultiParserPlugin.__new__(MultiParserPlugin)
    plugin.config = {}

    should_send, reason = plugin._video_send_decision(
        VideoSizeInfo(size_bytes=51 * 1024 * 1024)
    )

    assert should_send is False
    assert "超过限制 50.00 MB" in reason
