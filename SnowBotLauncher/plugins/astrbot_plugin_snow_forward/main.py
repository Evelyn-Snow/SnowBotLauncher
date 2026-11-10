"""合并转发阅读：把 Forward/Nodes 展开成文本，供合流和模型读取。

AstrBot 收到合并转发时只有 `Forward(id)`，不包含内容；本插件在合流之前调用
OneBot `get_forward_msg`，把节点转成「昵称：内容」文本，支持多层嵌套。
"""

from __future__ import annotations

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Face, Forward, Image, Node, Nodes, Plain, Record, Video
from astrbot.api.star import Context, Star
from astrbot.core.config.astrbot_config import AstrBotConfig

from .library import flatten_nodes, nested_forward_ids

NAME = "astrbot_plugin_snow_forward"
MARK = "[合并转发]"


class SnowForward(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.conf = config

    def _enabled(self) -> bool:
        return bool(self.conf.get("enabled", True))

    def _cfg(self, key: str, default):
        return self.conf.get(key, default)

    def _bot(self, event: AstrMessageEvent):
        bot = getattr(event, "bot", None)
        if bot is not None:
            return bot
        try:
            platform = self.context.get_platform("aiocqhttp")
            return getattr(platform, "bot", None) if platform is not None else None
        except Exception:
            return None

    async def _fetch(self, bot, forward_id: str, depth: int = 0) -> str:
        if not forward_id or depth > max(0, int(self._cfg("max_depth", 3))):
            return ""
        max_nodes = max(1, int(self._cfg("max_nodes", 60)))
        max_chars = max(500, int(self._cfg("max_chars", 6000)))
        try:
            payload = await bot.call_action("get_forward_msg", id=str(forward_id))
        except Exception as exc:
            logger.info(f"[{NAME}] 读取合并转发失败（{forward_id}）：{exc}")
            return ""
        messages = []
        if isinstance(payload, dict):
            messages = payload.get("messages") or []
            if not messages and isinstance(payload.get("data"), dict):
                messages = payload["data"].get("messages") or []
        messages = [item for item in messages if isinstance(item, dict)][:max_nodes]
        text = flatten_nodes(messages, limit_chars=max_chars)
        if depth < max(0, int(self._cfg("max_depth", 3))):
            for nested_id in nested_forward_ids(messages)[:5]:
                nested = await self._fetch(bot, nested_id, depth + 1)
                if nested:
                    text += "\n[嵌套转发]\n" + nested
        return text.strip()[:max_chars]

    @staticmethod
    def _node_components_text(nodes: Nodes) -> str:
        lines = []
        for node in nodes.nodes or []:
            if not isinstance(node, Node):
                continue
            name = str(node.name or "").strip()
            parts = []
            for comp in node.content or []:
                if isinstance(comp, Plain):
                    parts.append(str(comp.text or ""))
                elif isinstance(comp, Image):
                    parts.append("[图片]")
                elif isinstance(comp, Face):
                    parts.append(f"[表情:{comp.id}]")
                elif isinstance(comp, Video):
                    parts.append("[视频]")
                elif isinstance(comp, Record):
                    parts.append("[语音]")
                elif isinstance(comp, Forward):
                    parts.append("[嵌套转发]")
                elif isinstance(comp, Node):
                    parts.append("[嵌套转发]")
            body = "".join(parts).strip()
            if body:
                lines.append(f"{name}：{body}" if name else body)
        return "\n".join(lines)

    @filter.event_message_type(filter.EventMessageType.ALL, priority=(1 << 31) + 10)
    async def expand_forward(self, event: AstrMessageEvent):
        if not self._enabled():
            return
        if event.get_extra("_snow_forward_expanded"):
            return
        components = getattr(event.message_obj, "message", None) or []
        has_forward = any(isinstance(comp, (Forward, Nodes)) for comp in components)
        if not has_forward:
            return
        if any(
            isinstance(comp, Plain) and MARK in str(comp.text or "")
            for comp in components
        ):
            return
        bot = self._bot(event)
        if bot is None:
            return
        blocks = []
        for comp in components:
            if isinstance(comp, Forward):
                text = await self._fetch(bot, str(comp.id or ""), 0)
            elif isinstance(comp, Nodes):
                text = self._node_components_text(comp)
            else:
                continue
            if text:
                blocks.append(text)
        if not blocks:
            return
        block = "\n\n".join(blocks)
        max_chars = max(500, int(self._cfg("max_chars", 6000)))
        block = block[:max_chars]
        merged = f"{MARK}\n{block}"
        components.append(Plain("\n" + merged))
        event.message_str = (
            (str(event.message_str or "").strip() + "\n" + merged).strip()
        )
        if hasattr(event.message_obj, "message_str"):
            event.message_obj.message_str = event.message_str
        event.set_extra("_snow_forward_expanded", True)
        logger.info(
            f"[{NAME}] 已展开合并转发：{len(blocks)} 个，{len(block)} 字"
        )
