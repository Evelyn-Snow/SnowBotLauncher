"""QQ 分享卡片转文字：让模型“看见”群里/私聊分享的 B站视频、网页等卡片内容。

QQ 里分享链接时消息是 Json 卡片（没有纯文本），模型完全看不到——B站分享因此
石沉大海。本插件在消息处理最前端把卡片提取成「标题/内容/链接」纯文本追加到
消息里，下游的 BiliRead（B站阅读）、web_analyzer（网页分析）和读空气就都能看见了。
"""

from __future__ import annotations

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.message.components import Json, Plain

from .library import extract_share_text, merge_share_text

NAME = "astrbot_plugin_share_card"


class ShareCardText(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.conf = config

    @filter.event_message_type(filter.EventMessageType.ALL, priority=5)
    async def card_to_text(self, event: AstrMessageEvent):
        if not self.conf.get("enabled", True):
            return
        try:
            components = getattr(event.message_obj, "message", None) or []
            has_json = any(isinstance(c, Json) for c in components)
            if not has_json:
                return
            # 避免重复追加
            if any(
                isinstance(c, Plain) and "[分享卡片]" in str(c.text or "")
                for c in components
            ):
                return
            texts = []
            for comp in components:
                if not isinstance(comp, Json):
                    continue
                share = extract_share_text(comp.data)
                if share:
                    texts.append(share)
            if not texts:
                return
            share_text = "\n".join(texts)
            components.append(Plain("\n" + share_text))
            # 关键：同步纯文本字段，否则后续 LLM 阶段仍把消息当空文本跳过。
            event.message_str = merge_share_text(event.message_str, share_text)
            if hasattr(event.message_obj, "message_str"):
                event.message_obj.message_str = merge_share_text(
                    event.message_obj.message_str, share_text
                )
            logger.info(f"[{NAME}] 分享卡片已转为文字（{len(texts)} 张）")
        except Exception as exc:
            logger.warning(f"[{NAME}] 分享卡片处理失败: {exc}")
