"""对话优先：软化虚拟人生的状态约束，并在连续聊天时阻止她主动收尾。

不修改 virtual_life 源码：在它的 on_llm_request 之后（更低优先级）改写注入的
`<character_state>` 文本，把“普通回复必须与当前状态保持一致”换成“状态只作背景、
对话优先”；同时记录每个会话最近的消息时间，连续聊天时追加一段“先别结束对话”。

这样 virtual_life 升级也不会丢效果，补丁和连续对话逻辑都在一个插件里。
"""

from __future__ import annotations

import time

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Image
from astrbot.api.star import Context, Star
from astrbot.core.config.astrbot_config import AstrBotConfig

NAME = "astrbot_plugin_snow_chat_priority"

OLD_LINE = "普通回复必须与当前状态保持一致。"
SOFT_LINE = (
    "当前状态只作为语气和话题背景；对方来找你时以对话为先，"
    "不要主动说“先不聊了”，只有确实要睡觉、出门或上课迟到时，才自然地说晚点聊。"
)
SOFT_MARK = "[日程背景]"
PRIORITY_MARK = "[对话优先]"
SOFT_FALLBACK = (
    SOFT_MARK + " 上下文里的日程/状态只作语气和话题背景；"
    "对方来找你时以对话为先，不要用“我在忙”主动结束对话。"
)
PRIORITY_RULE = (
    PRIORITY_MARK + " 你们正在连续聊天（最近 {minutes} 分钟内已有 {turns} 条消息）。"
    "先别主动结束对话，也不要突然说“我先去忙了/晚点聊”；"
    "日程只当背景，等对话自然冷下来再去做自己的事。"
)


class SnowChatPriority(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.conf = config
        self._recent: dict[str, list[float]] = {}

    def _enabled(self) -> bool:
        return bool(self.conf.get("enabled", True))

    def _cfg(self, key: str, default):
        return self.conf.get(key, default)

    def _is_owner(self, event: AstrMessageEvent) -> bool:
        sender = str(getattr(event, "get_sender_id", lambda: "")() or "")
        if not sender:
            return False
        try:
            admins = {str(item) for item in self.context.get_config().get("admins_id") or []}
        except Exception:
            admins = set()
        return sender in admins

    @staticmethod
    def _replace_in_parts(req, old: str, new: str) -> bool:
        """改写 extra_user_content_parts 里的 TextPart / dict。"""
        changed = False
        parts = getattr(req, "extra_user_content_parts", None) or []
        for part in parts:
            if isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str) and old in text:
                    part["text"] = text.replace(old, new)
                    changed = True
                continue
            text = getattr(part, "text", None)
            if isinstance(text, str) and old in text:
                try:
                    part.text = text.replace(old, new)
                    changed = True
                except Exception:
                    pass
        return changed

    @staticmethod
    def _parts_contain(req, needle: str) -> bool:
        for part in getattr(req, "extra_user_content_parts", None) or []:
            text = part.get("text") if isinstance(part, dict) else getattr(part, "text", None)
            if isinstance(text, str) and needle in text:
                return True
        return False

    def _track_turns(self, event: AstrMessageEvent) -> tuple[int, int]:
        """记录本条消息，返回 (窗口内消息数, 使用的窗口分钟)。"""
        umo = str(getattr(event, "unified_msg_origin", "") or "")
        now = time.time()
        owner = self._is_owner(event)
        window = max(
            1,
            int(
                self._cfg(
                    "owner_window_minutes" if owner else "active_window_minutes",
                    5 if owner else 10,
                )
            ),
        )
        stamps = self._recent.setdefault(umo, [])
        stamps.append(now)
        cutoff = now - window * 60
        self._recent[umo] = [ts for ts in stamps if ts >= cutoff]
        if len(self._recent) > 200:
            for key in list(self._recent)[:20]:
                self._recent.pop(key, None)
        return len(self._recent[umo]), window

    @filter.on_llm_request(priority=-(1 << 29))
    async def apply_chat_priority(self, event: AstrMessageEvent, req):
        if not self._enabled():
            return
        prompt = str(getattr(req, "system_prompt", "") or "")
        changed = False

        # A：软化 virtual_life 的硬性状态约束
        if bool(self._cfg("soften_virtual_life", True)):
            softened_old = self._replace_in_parts(req, OLD_LINE, SOFT_LINE)
            if OLD_LINE in prompt:
                prompt = prompt.replace(OLD_LINE, SOFT_LINE)
                softened_old = True
            if softened_old:
                changed = True
                logger.info(f"[{NAME}] 已软化虚拟人生状态约束")
            else:
                has_state = "可打扰度" in prompt or self._parts_contain(req, "可打扰度")
                if has_state and SOFT_MARK not in prompt:
                    prompt = prompt + "\n\n" + SOFT_FALLBACK
                    changed = True
                    logger.info(f"[{NAME}] 已追加日程背景说明")

        # 文字 + 图片混发时，提醒两边都要看
        if bool(self._cfg("mixed_media_hint", True)) and "[多模态]" not in prompt:
            components = getattr(event.message_obj, "message", None) or []
            has_image = any(isinstance(comp, Image) for comp in components)
            if has_image and str(getattr(event, "message_str", "") or "").strip():
                prompt = prompt + (
                    chr(10) * 2
                    + "[多模态] 这条消息里文字和图片是一起的：文字是对方的话，图片是补充。"
                    "回答时两部分都要看，不要只描述图片或只回文字。"
                )
                changed = True
                logger.info(f"[{NAME}] 已追加多模态提示（文字+图片）")

        # D：连续聊天时明确要求先别收尾
        turns, window = self._track_turns(event)
        owner = self._is_owner(event)
        need = max(
            1,
            int(self._cfg("owner_min_turns" if owner else "min_turns", 1 if owner else 2)),
        )
        if turns >= need and PRIORITY_MARK not in prompt:
            prompt = prompt + "\n\n" + PRIORITY_RULE.format(minutes=window, turns=turns)
            changed = True
            logger.info(
                f"[{NAME}] 连续对话优先（{turns} 条 / {window} 分钟，"
                f"{'主人私聊' if owner else '普通会话'}）"
            )

        if changed:
            req.system_prompt = prompt
