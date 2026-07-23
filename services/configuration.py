from collections.abc import Mapping

from astrbot.api import logger

from ..core.parser import BaseParser
from ..platforms import (
    BilibiliParser,
    DouyinParser,
    RedBookParser,
    TiebaParser,
    WeChatParser,
    WeiboParser,
    XiaoheiheParser,
    ZhihuParser,
)

PARSER_TYPES: tuple[type[BaseParser], ...] = (
    BilibiliParser,
    DouyinParser,
    RedBookParser,
    TiebaParser,
    WeiboParser,
    WeChatParser,
    XiaoheiheParser,
    ZhihuParser,
)


def build_parsers(config) -> dict[str, BaseParser]:
    """按稳定优先级创建所有平台解析器。"""
    return {parser_type.name: parser_type(config) for parser_type in PARSER_TYPES}


def migrate_platform_switches(config, parsers: Mapping[str, BaseParser]) -> None:
    """将旧版启用列表一次性迁移为独立平台开关。"""
    switches = config.get("platform_switches")
    if not isinstance(switches, dict) or bool(
        config.get("platform_switches_migrated", False)
    ):
        return

    legacy_platforms = config.get("enabled_platforms", [])
    enabled = (
        {str(item).lower() for item in legacy_platforms}
        if isinstance(legacy_platforms, list)
        else set(parsers)
    )
    for name in parsers:
        switches[name] = name in enabled
    config["platform_switches_migrated"] = True

    save_config = getattr(config, "save_config", None)
    if callable(save_config):
        try:
            save_config()
        except Exception as exc:
            logger.warning(f"保存平台开关迁移结果失败: {exc}")


def enabled_parsers(config, parsers: Mapping[str, BaseParser]) -> list[BaseParser]:
    """按注册顺序返回当前启用的平台解析器。"""
    switches = config.get("platform_switches")
    if isinstance(switches, dict):
        return [
            parser for name, parser in parsers.items() if bool(switches.get(name, True))
        ]

    legacy_platforms = config.get("enabled_platforms", [])
    enabled = (
        {str(item).lower() for item in legacy_platforms}
        if isinstance(legacy_platforms, list)
        else set()
    )
    return [parser for name, parser in parsers.items() if name in enabled]
