import re
from dataclasses import dataclass

import httpx

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Node, Nodes
from astrbot.api.star import Context, Star

from .models import BaseParser, ParseResult
from .platforms import BilibiliParser, DouyinParser, RedBookParser
from .utils import extract_context


@dataclass
class VideoSizeInfo:
    size_bytes: int | None = None
    reason: str = ""

    @property
    def size_mb(self) -> float | None:
        if self.size_bytes is None:
            return None
        return self.size_bytes / 1024 / 1024


class MultiParserPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.parsers: dict[str, BaseParser] = {
            "bilibili": BilibiliParser(config),
            "douyin": DouyinParser(config),
            "redbook": RedBookParser(config),
        }

    def _enabled_parsers(self) -> list[BaseParser]:
        enabled = {
            str(item).lower() for item in self.config.get("enabled_platforms", [])
        }
        return [parser for name, parser in self.parsers.items() if name in enabled]

    @staticmethod
    async def _call_onebot(event: AstrMessageEvent, action: str, **params):
        bot = getattr(event, "bot", None)
        if bot and hasattr(bot, "call_action"):
            return await bot.call_action(action, **params)
        if bot and hasattr(bot, "call_api"):
            return await bot.call_api(action, **params)
        raise RuntimeError("当前事件没有可用的 OneBot 客户端")

    @staticmethod
    def _raw(event: AstrMessageEvent):
        return getattr(event.message_obj, "raw_message", None)

    def _message_id(self, event: AstrMessageEvent) -> str:
        raw = self._raw(event) or {}
        message_id = raw.get("message_id") if isinstance(raw, dict) else ""
        return str(message_id or getattr(event.message_obj, "message_id", "") or "")

    async def _react_success(self, event: AstrMessageEvent) -> None:
        if not bool(self.config.get("enable_parse_reaction", True)):
            return

        message_id = self._message_id(event)
        if not message_id:
            logger.info("解析成功表情回应失败: 未获取到 message_id")
            return

        action = str(self.config.get("reaction_action", "set_msg_emoji_like")).strip()
        emoji_id = str(self.config.get("reaction_emoji_id", "124")).strip()
        if not action or not emoji_id:
            return

        try:
            await self._call_onebot(
                event, action, message_id=int(message_id), emoji_id=emoji_id
            )
        except Exception as exc:
            logger.info(f"解析成功表情回应失败: {exc}")

    @staticmethod
    def _format_size(size_mb: float | None) -> str:
        if size_mb is None:
            return "未知"
        return f"{size_mb:.2f} MB"

    @staticmethod
    def _parse_content_range(value: str) -> int | None:
        match = re.search(r"/(\d+)\s*$", value)
        if not match:
            return None
        return int(match.group(1))

    async def _probe_video_size(self, url: str) -> VideoSizeInfo:
        timeout = float(
            self.config.get(
                "size_check_timeout_seconds",
                self.config.get("request_timeout_seconds", 30),
            )
        )
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "*/*",
        }
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=True, headers=headers
        ) as client:
            # 优先使用 HEAD 获取大小，避免为探测文件长度下载视频正文。
            try:
                response = await client.head(url)
                length = response.headers.get("Content-Length")
                if length and length.isdigit():
                    return VideoSizeInfo(size_bytes=int(length))
            except Exception as exc:
                logger.info(f"HEAD 检查视频大小失败，尝试 Range 请求: {exc}")

            # 部分服务器不支持 HEAD，退回单字节 Range 请求并读取完整文件大小。
            try:
                async with client.stream(
                    "GET", url, headers={"Range": "bytes=0-0"}
                ) as response:
                    content_range = response.headers.get("Content-Range", "")
                    size = self._parse_content_range(content_range)
                    if size is not None:
                        return VideoSizeInfo(size_bytes=size)
                    length = response.headers.get("Content-Length")
                    if length and length.isdigit():
                        length_bytes = int(length)
                        if length_bytes > 1:
                            return VideoSizeInfo(size_bytes=length_bytes)
                        return VideoSizeInfo(reason="服务端未返回完整文件大小")
            except Exception as exc:
                return VideoSizeInfo(reason=f"视频大小检查失败: {exc}")

        return VideoSizeInfo(reason="服务端未返回视频大小")

    def _video_send_decision(self, size_info: VideoSizeInfo) -> tuple[bool, str]:
        max_size_mb = float(self.config.get("max_video_size_mb", 50))
        if max_size_mb <= 0:
            return True, "未启用大小限制"

        if size_info.size_mb is None:
            if bool(self.config.get("allow_unknown_video_size", False)):
                return True, "视频大小未知，已按配置允许发送"
            reason = size_info.reason or "视频大小未知"
            return False, f"{reason}，已改用合并转发发送解析链接"

        if size_info.size_mb > max_size_mb:
            return False, (
                f"视频大小 {self._format_size(size_info.size_mb)} "
                f"超过限制 {max_size_mb:.2f} MB，已改用合并转发发送解析链接"
            )

        return True, f"视频大小 {self._format_size(size_info.size_mb)}，未超过限制"

    async def _send_forward_links(
        self, event: AstrMessageEvent, result: ParseResult, reason: str
    ) -> None:
        sender_id = str(event.get_sender_id() or "0")
        sender_name = sender_id
        raw = self._raw(event) or {}
        raw_sender = raw.get("sender") or {}
        if isinstance(raw_sender, dict):
            sender_name = (
                raw_sender.get("card") or raw_sender.get("nickname") or sender_name
            )

        title = result.title or "未命名内容"
        summary_lines = [
            f"{result.platform} 解析链接",
            f"标题: {title}",
        ]
        if result.author:
            summary_lines.append(f"作者: {result.author}")
        if reason:
            summary_lines.append(f"说明: {reason}")

        nodes = [
            {
                "type": "node",
                "data": {
                    "name": sender_name,
                    "uin": sender_id,
                    "content": [
                        {"type": "text", "data": {"text": "\n".join(summary_lines)}}
                    ],
                },
            },
            {
                "type": "node",
                "data": {
                    "name": sender_name,
                    "uin": sender_id,
                    "content": [
                        {
                            "type": "text",
                            "data": {"text": f"视频直链:\n{result.video_url}"},
                        }
                    ],
                },
            },
        ]

        group_id = raw.get("group_id")
        if group_id:
            await self._call_onebot(
                event, "send_group_forward_msg", group_id=int(group_id), messages=nodes
            )
            return

        user_id = raw.get("user_id") or sender_id
        await self._call_onebot(
            event, "send_private_forward_msg", user_id=int(user_id), messages=nodes
        )

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def handle_parse(self, event: AstrMessageEvent):
        context = extract_context(event)
        if not context.combined_text:
            return

        # 解析器按配置顺序尝试匹配；命中后即完成处理，避免同一链接被重复解析。
        for parser in self._enabled_parsers():
            try:
                if not await parser.match(context):
                    continue
                await self._react_success(event)
                result = await parser.parse(context)
                send_video_by_url = bool(self.config.get("send_video_by_url", True))
                include_video_url = not send_video_by_url
                supports_forward_nodes = False
                if result.image_count >= 3:
                    try:
                        platform_name = event.get_platform_name()
                    except Exception:
                        platform_name = ""
                    supports_forward_nodes = platform_name in {
                        "aiocqhttp",
                        "satori",
                    }
                # 多图内容在支持节点消息的平台上使用合并转发，以保留图文顺序并减少刷屏。
                if result.image_count >= 3 and supports_forward_nodes:
                    summary_chain = result.info_chain(
                        include_content=False,
                        include_video_url=include_video_url,
                    )
                    if summary_chain:
                        yield event.chain_result(summary_chain)

                    content_chain = result.info_chain(
                        include_summary=False,
                        include_video_url=include_video_url,
                    )
                    if content_chain:
                        sender_id = str(event.get_sender_id() or "0")
                        try:
                            public_sender_name = event.get_sender_name()
                        except Exception:
                            public_sender_name = ""
                        sender_name = (
                            str(public_sender_name) if public_sender_name else sender_id
                        )
                        raw = self._raw(event) or {}
                        raw_sender = (
                            raw.get("sender") or {} if isinstance(raw, dict) else {}
                        )
                        if isinstance(raw_sender, dict) and raw_sender.get("card"):
                            sender_name = str(raw_sender["card"])
                        nodes = []
                        if summary_chain:
                            nodes.append(
                                Node(
                                    content=summary_chain,
                                    name=sender_name,
                                    uin=sender_id,
                                )
                            )
                        nodes.extend(
                            Node(
                                content=[component],
                                name=sender_name,
                                uin=sender_id,
                            )
                            for component in content_chain
                        )
                        yield event.chain_result([Nodes(nodes)])
                else:
                    info_chain = result.info_chain(
                        include_video_url=include_video_url
                    )
                    if info_chain:
                        yield event.chain_result(info_chain)
                # 视频直发前先检查大小；超限或无法确认大小时按配置转发解析链接。
                if send_video_by_url and result.video_url:
                    size_info = await self._probe_video_size(result.video_url)
                    should_send_video, reason = self._video_send_decision(size_info)
                    if should_send_video:
                        yield event.chain_result(result.video_chain())
                    else:
                        try:
                            await self._send_forward_links(event, result, reason)
                        except Exception as exc:
                            logger.warning(f"合并转发解析链接失败: {exc}")
                            yield event.plain_result(
                                f"{reason}\n合并转发发送失败: {exc}\n视频链接: {result.video_url}"
                            )
                elif result.video_url:
                    try:
                        await self._send_forward_links(
                            event, result, "已按配置不直接发送视频"
                        )
                    except Exception as exc:
                        logger.warning(f"合并转发解析链接失败: {exc}")
                        yield event.plain_result(
                            f"合并转发发送失败: {exc}\n视频链接: {result.video_url}"
                        )
                return
            except Exception as exc:
                logger.warning(f"{parser.name} 解析失败: {exc}")
                yield event.plain_result(f"{parser.name} 解析失败: {exc}")
                return
