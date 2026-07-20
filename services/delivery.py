from collections.abc import Mapping

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.message_components import Node, Nodes, Plain

from ..core.contracts import ParseResult


class DeliveryService:
    """封装 AstrBot 消息组件编排与 OneBot 平台调用。"""

    FORWARD_NODE_PLATFORMS = {"aiocqhttp", "satori"}
    FORWARD_MODES = {"always", "threshold", "never"}
    DEFAULT_FORWARD_MODE = "threshold"
    DEFAULT_IMAGE_THRESHOLD = 2
    DEFAULT_TEXT_THRESHOLD = 200

    def __init__(self, config: Mapping[str, object]) -> None:
        self.config = config

    @staticmethod
    async def call_onebot(event: AstrMessageEvent, action: str, **params):
        bot = getattr(event, "bot", None)
        if bot and hasattr(bot, "call_action"):
            return await bot.call_action(action, **params)
        if bot and hasattr(bot, "call_api"):
            return await bot.call_api(action, **params)
        raise RuntimeError("当前事件没有可用的 OneBot 客户端")

    @staticmethod
    def raw_message(event: AstrMessageEvent):
        return getattr(event.message_obj, "raw_message", None)

    def message_id(self, event: AstrMessageEvent) -> str:
        raw = self.raw_message(event) or {}
        message_id = raw.get("message_id") if isinstance(raw, dict) else ""
        fallback = getattr(event.message_obj, "message_id", "")
        return str(message_id or fallback or "")

    async def react_success(self, event: AstrMessageEvent) -> None:
        if not bool(self.config.get("enable_parse_reaction", True)):
            return

        message_id = self.message_id(event)
        if not message_id:
            logger.info("解析成功表情回应失败: 未获取到 message_id")
            return

        action = str(self.config.get("reaction_action", "set_msg_emoji_like")).strip()
        emoji_id = str(self.config.get("reaction_emoji_id", "124")).strip()
        if not action or not emoji_id:
            return

        try:
            await self.call_onebot(
                event, action, message_id=int(message_id), emoji_id=emoji_id
            )
        except Exception as exc:
            logger.info(f"解析成功表情回应失败: {exc}")

    def build_content_results(
        self,
        event: AstrMessageEvent,
        result: ParseResult,
        *,
        include_video_url: bool,
    ) -> list:
        info_chain = result.info_chain(include_video_url=include_video_url)
        if not info_chain:
            return []
        if not self._should_forward_content(event, result, info_chain):
            return [event.chain_result(info_chain)]

        summary_chain = result.info_chain(
            include_content=False,
            include_video_url=include_video_url,
        )
        content_chain = result.info_chain(
            include_summary=False,
            include_video_url=include_video_url,
        )
        sender_name, sender_id = self.sender_identity(event)
        nodes = [
            Node(content=[component], name=sender_name, uin=sender_id)
            for component in [*summary_chain, *content_chain]
        ]
        return [event.chain_result([Nodes(nodes)])]

    def _should_forward_content(
        self,
        event: AstrMessageEvent,
        result: ParseResult,
        chain: list,
    ) -> bool:
        if not self._supports_forward_nodes(event):
            return False

        mode = str(
            self.config.get("forward_mode", self.DEFAULT_FORWARD_MODE)
        ).strip().lower()
        if mode not in self.FORWARD_MODES:
            mode = self.DEFAULT_FORWARD_MODE
        if mode == "always":
            return True
        if mode == "never":
            return False

        image_threshold = self._non_negative_int(
            self.config.get(
                "forward_image_threshold", self.DEFAULT_IMAGE_THRESHOLD
            ),
            self.DEFAULT_IMAGE_THRESHOLD,
        )
        text_threshold = self._non_negative_int(
            self.config.get("forward_text_threshold", self.DEFAULT_TEXT_THRESHOLD),
            self.DEFAULT_TEXT_THRESHOLD,
        )
        text_length = sum(
            len(component.text) for component in chain if isinstance(component, Plain)
        )
        return result.image_count > image_threshold or text_length > text_threshold

    @staticmethod
    def _non_negative_int(value: object, default: int) -> int:
        try:
            return max(int(value), 0)
        except (TypeError, ValueError):
            return default

    async def send_forward_links(
        self, event: AstrMessageEvent, result: ParseResult, reason: str
    ) -> None:
        sender_name, sender_id = self.sender_identity(event, prefer_raw_nickname=True)
        summary_lines = [
            f"{result.platform} 解析链接",
            f"标题: {result.title or '未命名内容'}",
        ]
        if result.author:
            summary_lines.append(f"作者: {result.author}")
        if reason:
            summary_lines.append(f"说明: {reason}")

        nodes = [
            self._raw_forward_node(sender_name, sender_id, "\n".join(summary_lines)),
            self._raw_forward_node(
                sender_name, sender_id, f"视频直链:\n{result.video_url}"
            ),
        ]
        raw = self.raw_message(event)
        raw = raw if isinstance(raw, dict) else {}
        group_id = raw.get("group_id")
        if group_id:
            await self.call_onebot(
                event,
                "send_group_forward_msg",
                group_id=int(group_id),
                messages=nodes,
            )
            return

        user_id = raw.get("user_id") or sender_id
        await self.call_onebot(
            event,
            "send_private_forward_msg",
            user_id=int(user_id),
            messages=nodes,
        )

    def sender_identity(
        self,
        event: AstrMessageEvent,
        *,
        prefer_raw_nickname: bool = False,
    ) -> tuple[str, str]:
        sender_id = str(event.get_sender_id() or "0")
        try:
            public_name = event.get_sender_name()
        except Exception:
            public_name = ""
        sender_name = str(public_name) if public_name else sender_id

        raw = self.raw_message(event)
        raw_sender = raw.get("sender") or {} if isinstance(raw, dict) else {}
        if isinstance(raw_sender, dict):
            raw_name = raw_sender.get("card")
            if prefer_raw_nickname:
                raw_name = raw_name or raw_sender.get("nickname")
            if raw_name:
                sender_name = str(raw_name)
        return sender_name, sender_id

    @classmethod
    def _supports_forward_nodes(cls, event: AstrMessageEvent) -> bool:
        try:
            platform_name = event.get_platform_name()
        except Exception:
            return False
        return platform_name in cls.FORWARD_NODE_PLATFORMS

    @staticmethod
    def _raw_forward_node(name: str, user_id: str, text: str) -> dict:
        return {
            "type": "node",
            "data": {
                "name": name,
                "uin": user_id,
                "content": [{"type": "text", "data": {"text": text}}],
            },
        }
