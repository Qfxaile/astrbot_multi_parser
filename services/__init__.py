"""插件应用服务。"""

from .configuration import build_parsers, enabled_parsers, migrate_platform_switches
from .delivery import DeliveryService
from .video import VideoSendPolicy, VideoSizeInfo, VideoSizeProbe

__all__ = [
    "DeliveryService",
    "VideoSendPolicy",
    "VideoSizeInfo",
    "VideoSizeProbe",
    "build_parsers",
    "enabled_parsers",
    "migrate_platform_switches",
]
