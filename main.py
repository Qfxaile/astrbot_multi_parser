import httpx as httpx
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star

from .core.contracts import ParseResult
from .core.http import CookieAccessError
from .services.configuration import (
    build_parsers,
    enabled_parsers,
    migrate_platform_switches,
)
from .services.delivery import DeliveryService
from .services.video import (
    VideoSendPolicy,
    VideoSizeInfo,
    VideoSizeProbe,
    format_video_size,
    parse_content_range,
)
from .utils import extract_context

__all__ = ["MultiParserPlugin", "VideoSizeInfo"]


class MultiParserPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.parsers = build_parsers(config)
        self._delivery = DeliveryService(config)
        self._migrate_platform_switches()

    def _delivery_service(self) -> DeliveryService:
        delivery = getattr(self, "_delivery", None)
        if delivery is None:
            delivery = DeliveryService(self.config)
            self._delivery = delivery
        return delivery

    def _migrate_platform_switches(self) -> None:
        migrate_platform_switches(self.config, self.parsers)

    def _enabled_parsers(self):
        return enabled_parsers(self.config, self.parsers)

    @staticmethod
    async def _call_onebot(event: AstrMessageEvent, action: str, **params):
        return await DeliveryService.call_onebot(event, action, **params)

    @staticmethod
    def _raw(event: AstrMessageEvent):
        return DeliveryService.raw_message(event)

    def _message_id(self, event: AstrMessageEvent) -> str:
        return self._delivery_service().message_id(event)

    async def _react_success(self, event: AstrMessageEvent) -> None:
        await self._delivery_service().react_success(event)

    @staticmethod
    def _format_size(size_mb: float | None) -> str:
        return format_video_size(size_mb)

    @staticmethod
    def _parse_content_range(value: str) -> int | None:
        return parse_content_range(value)

    async def _probe_video_size(self, url: str) -> VideoSizeInfo:
        return await VideoSizeProbe(self.config).probe(url)

    def _video_send_decision(self, size_info: VideoSizeInfo) -> tuple[bool, str]:
        return VideoSendPolicy(self.config).decide(size_info)

    async def _send_forward_links(
        self, event: AstrMessageEvent, result: ParseResult, reason: str
    ) -> None:
        await self._delivery_service().send_forward_links(event, result, reason)

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def handle_parse(self, event: AstrMessageEvent):
        context = extract_context(event)
        if not context.combined_text:
            return

        for parser in self._enabled_parsers():
            result: ParseResult | None = None
            try:
                if not await parser.match(context):
                    continue
                await self._react_success(event)
                result = await parser.parse(context)
                send_video_by_url = bool(self.config.get("send_video_by_url", True))
                should_send_video = False
                video_reason = ""
                if send_video_by_url and result.video_url:
                    size_info = await self._probe_video_size(result.video_url)
                    should_send_video, video_reason = self._video_send_decision(
                        size_info
                    )

                content_results, video_embedded = (
                    self._delivery_service().build_content_delivery(
                        event,
                        result,
                        include_video_url=not send_video_by_url,
                        include_video=should_send_video,
                    )
                )
                delivery = self._delivery_service()
                if delivery.is_forward_delivery(content_results):
                    try:
                        await delivery.send_forward_results(
                            event, content_results, result
                        )
                    except Exception as exc:
                        logger.warning(f"{parser.name} 合并转发发送失败: {exc}")
                        yield event.plain_result(
                            f"{parser.name} 合并转发发送失败: {exc}"
                        )
                        return
                else:
                    for message in content_results:
                        yield message

                if send_video_by_url and result.video_url:
                    if should_send_video and not video_embedded:
                        yield event.chain_result(result.video_chain())
                    elif not should_send_video:
                        async for fallback in self._forward_with_fallback(
                            event, result, video_reason
                        ):
                            yield fallback
                elif result.video_url:
                    async for fallback in self._forward_with_fallback(
                        event, result, "已按配置不直接发送视频"
                    ):
                        yield fallback
                return
            except CookieAccessError as exc:
                logger.warning(f"{parser.name} Cookie 访问失败: {exc}")
                yield event.plain_result(str(exc))
                return
            except Exception as exc:
                logger.warning(f"{parser.name} 解析失败: {exc}")
                yield event.plain_result(f"{parser.name} 解析失败: {exc}")
                return
            finally:
                if result is not None:
                    result.cleanup_temporary_files()

    async def _forward_with_fallback(
        self,
        event: AstrMessageEvent,
        result: ParseResult,
        reason: str,
    ):
        try:
            await self._send_forward_links(event, result, reason)
        except Exception as exc:
            logger.warning(f"合并转发解析链接失败: {exc}")
            yield event.plain_result(
                f"{reason}\n合并转发发送失败: {exc}\n视频链接: {result.video_url}"
            )
