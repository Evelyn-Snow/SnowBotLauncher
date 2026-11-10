"""小雪消息合流：把连续发来的几句话并成一次理解和回复。

很多“对话不连贯”不是模型不会接，而是一条消息一次请求：用户话没说完，
她已经回了第一句，后半句又变成新一轮。这里在最高优先级先收住消息，
等一个很短的可刷新窗口，把同一 burst 的消息合成一条再重新入队：

- 每条新消息把等待窗口刷到 now + wait_seconds，最长不超过 max_wait_seconds
- 用轻量连续性评分决定要不要延长窗口（追问、话没说完、同话题才延长）
- 窗口结束后按连续性分组、按条数切块，逐块交给正常 AstrBot 流程
- 同时在 on_llm_request 里合并历史中相邻的 user 消息，避免旧碎片继续干扰

只处理非命令消息；私聊和群聊都支持（群聊按发送者各自成组，窗口更短）。
webchat 默认不接管，避免影响网页 SSE。
"""

from __future__ import annotations

import asyncio
import inspect
import time
from dataclasses import dataclass, field

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import (
    At,
    Face,
    File,
    Image,
    Json,
    Plain,
    Poke,
    Record,
    Reply,
    Video,
)
from astrbot.api.star import Context, Star
from astrbot.core.config.astrbot_config import AstrBotConfig

from .library import (
    chunk_parts,
    continuity_score,
    face_label,
    group_parts,
    merge_contexts,
    merge_texts,
    merged_messages_hint,
    should_extend,
    split_face_markers,
)

NAME = "astrbot_plugin_snow_burst"
_MEDIA = (Image, Record, File, Video, Json)
# Face 不进合流链：文本里已渲染 [表情:名]，链里再留原件会和文本重复
_KEEP = (Image, Record, File, Video, Json, At, Reply, Poke)


def _face_text(event: AstrMessageEvent, existing: str = "") -> str:
    """把消息链里的 QQ 小黄脸渲染成 [表情:名]；已有文本里出现过的不再重复。"""
    components = getattr(event.message_obj, "message", None) or []
    labels = []
    for comp in components:
        if isinstance(comp, Face):
            label = face_label(comp.id)
            if label and label not in existing:
                labels.append(label)
    return " ".join(labels)


@dataclass
class _Part:
    event: AstrMessageEvent
    text: str
    ts: float


@dataclass
class _Burst:
    key: str
    first_ts: float
    deadline: float
    parts: list[_Part] = field(default_factory=list)
    task: asyncio.Task | None = None


class SnowBurst(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.conf = config
        self._bursts: dict[str, _Burst] = {}

    def _enabled(self, event: AstrMessageEvent) -> bool:
        if not bool(self.conf.get("enabled", False)):
            return False
        raw = str(self.conf.get("enabled_platforms") or "aiocqhttp")
        names = {
            item.strip()
            for item in raw.replace("，", ",").split(",")
            if item.strip()
        }
        return event.get_platform_name() in names

    def _wait(self, private: bool = True) -> float:
        key = "wait_seconds" if private else "group_wait_seconds"
        default = 3.0 if private else 2.0
        return max(0.5, float(self.conf.get(key) or default))

    def _max_wait(self, private: bool = True) -> float:
        key = "max_wait_seconds" if private else "group_max_wait_seconds"
        default = 12.0 if private else 8.0
        return max(self._wait(private), float(self.conf.get(key) or default))

    def _threshold(self) -> float:
        return float(self.conf.get("continuity_threshold") or 0.18)

    def _max_messages(self) -> int:
        return max(1, int(self.conf.get("max_messages") or 8))

    @filter.event_message_type(
        filter.EventMessageType.ALL, priority=(1 << 31)
    )
    async def collect(self, event: AstrMessageEvent):
        if not self._enabled(event):
            return
        if event.get_extra("_snow_burst_merged"):
            return
        if str(event.get_sender_id() or "") == str(event.get_self_id() or ""):
            return
        if event.get_platform_name() == "webchat":
            return

        text = str(event.message_str or "").strip()
        faces = _face_text(event, text)
        if faces:
            # message_str 不含表情：补进文本，纯表情消息才不会被当成空消息跳过
            text = f"{text} {faces}".strip() if text else faces
        if text.startswith(("/", "！", "!")):
            return
        components = getattr(event.message_obj, "message", None) or []
        has_media = any(isinstance(comp, _MEDIA) for comp in components)
        if not text and not has_media:
            return

        private = event.is_private_chat()
        if not private and not bool(self.conf.get("group_enabled", True)):
            return
        if bool(self.conf.get("private_only", False)) and not private:
            return

        now = time.monotonic()
        key = f"{event.unified_msg_origin}|{event.get_sender_id() or ''}"
        wait = self._wait(private)
        max_wait = self._max_wait(private)
        part = _Part(event=event, text=text, ts=now)
        burst = self._bursts.get(key)
        if burst is None:
            burst = _Burst(key=key, first_ts=now, deadline=now + wait)
            self._bursts[key] = burst
        else:
            score = continuity_score(burst.parts[-1].text, text)
            cap = burst.first_ts + (
                max_wait if should_extend(score, self._threshold()) else wait
            )
            burst.deadline = min(now + wait, cap)
            logger.info(
                f"[{NAME}] 续窗 {score:.2f}，{len(burst.parts) + 1} 条：{text[:40]!r}"
            )
        burst.parts.append(part)
        if len(burst.parts) >= self._max_messages():
            burst.deadline = now + 0.15
        if burst.task is None or burst.task.done():
            burst.task = asyncio.create_task(self._flush_later(key))

        # 先挡住这一条，等合流后再重新入队；share_card 等插件会在新事件里正常执行。
        event.stop_event()

    async def _flush_later(self, key: str) -> None:
        while True:
            burst = self._bursts.get(key)
            if burst is None:
                return
            delay = burst.deadline - time.monotonic()
            if delay <= 0:
                break
            await asyncio.sleep(delay)
        await self._flush(key)

    async def _flush(self, key: str) -> None:
        burst = self._bursts.pop(key, None)
        if burst is None:
            return
        parts = [
            {"event": part.event, "text": part.text, "ts": part.ts}
            for part in burst.parts
        ]
        if bool(self.conf.get("coalesce_block", True)):
            try:
                await self._dispatch(parts)
            except Exception as exc:
                logger.warning(f"[{NAME}] 整块合流派发失败，回退最后一条：{exc}")
                last = parts[-1]["event"]
                try:
                    last.continue_event()
                    last.clear_result()
                    last.set_extra("_snow_burst_merged", True)
                    queue = self._event_queue()
                    if queue is None:
                        raise RuntimeError("找不到事件队列")
                    queue.put_nowait(last)
                except Exception as fallback_exc:
                    logger.error(
                        f"[{NAME}] 回退派发也失败，消息丢失：{fallback_exc}"
                    )
            return
        groups = group_parts(
            parts,
            gap_seconds=2.0,
            threshold=self._threshold(),
        )
        for group in groups:
            for chunk in chunk_parts(group, self._max_messages()):
                try:
                    await self._dispatch(chunk)
                except Exception as exc:
                    logger.warning(f"[{NAME}] 合流派发失败，回退最后一条：{exc}")
                    last = chunk[-1]["event"]
                    try:
                        last.continue_event()
                        last.clear_result()
                        last.set_extra("_snow_burst_merged", True)
                        queue = self._event_queue()
                        if queue is None:
                            raise RuntimeError("找不到事件队列")
                        queue.put_nowait(last)
                    except Exception as fallback_exc:
                        logger.error(
                            f"[{NAME}] 回退派发也失败，消息丢失：{fallback_exc}"
                        )
                await asyncio.sleep(0.05)

    def _event_queue(self):
        getter = getattr(self.context, "get_event_queue", None)
        if callable(getter):
            try:
                return getter()
            except Exception:
                pass
        return getattr(self.context, "_event_queue", None)

    async def _dispatch(self, parts: list[dict]) -> None:
        if not parts:
            return
        original: AstrMessageEvent = parts[-1]["event"]
        text = merge_texts([str(part.get("text") or "") for part in parts])
        chain = []
        text_added = False
        for part in parts:
            for comp in getattr(part["event"].message_obj, "message", None) or []:
                if isinstance(comp, Plain):
                    if not text_added and text:
                        chain.append(Plain(text))
                        text_added = True
                elif isinstance(comp, _KEEP):
                    # 保留 At / Reply / 图片 / 卡片，群聊 @ 和引用才能继续被识别
                    chain.append(comp)
        if text and not text_added:
            chain.insert(0, Plain(text))
        if not chain:
            return
        original.message_obj.message_str = text
        original.message_obj.message = chain

        # 尽量新建一个事件，避免复用已经 stop 过的旧 trace/状态；构造失败才退回旧对象。
        event = original
        try:
            cls = type(original)
            args = [
                text,
                original.message_obj,
                original.platform_meta,
                original.session_id,
            ]
            if "bot" in inspect.signature(cls).parameters:
                args.append(getattr(original, "bot", None))
            event = cls(*args)
        except Exception as exc:
            logger.info(f"[{NAME}] 新建事件失败，复用原事件：{exc}")
            event.continue_event()
            event.clear_result()
        event.message_str = text
        event.message_obj.message_str = text
        event.message_obj.message = chain
        event.set_extra("_snow_burst_merged", True)
        event.set_extra("_snow_burst_count", len(parts))
        event.set_extra(
            "_snow_burst_image_count",
            sum(
                1
                for part in parts
                for comp in getattr(part["event"].message_obj, "message", None) or []
                if isinstance(comp, Image)
            ),
        )
        queue = self._event_queue()
        if queue is None:
            logger.warning(f"[{NAME}] 找不到事件队列，消息未重新入队")
            return
        queue.put_nowait(event)
        logger.info(f"[{NAME}] 合流 {len(parts)} 条 → {text[:80]!r}")

    @filter.on_llm_request()
    async def hint_merged_messages(self, event: AstrMessageEvent, req):
        if not bool(self.conf.get("enabled", False)):
            return
        if not bool(self.conf.get("merge_hint", True)):
            return
        if not event.get_extra("_snow_burst_merged"):
            return
        try:
            count = int(event.get_extra("_snow_burst_count") or 0)
        except (TypeError, ValueError):
            count = 0
        if count < 2:
            return
        prompt = str(getattr(req, "system_prompt", "") or "")
        if "[连续消息]" in prompt:
            return
        try:
            image_count = int(event.get_extra("_snow_burst_image_count") or 0)
        except (TypeError, ValueError):
            image_count = 0
        req.system_prompt = (
            prompt + chr(10) * 2 + merged_messages_hint(count, image_count)
        )

    @filter.on_llm_request()
    async def merge_history(self, event: AstrMessageEvent, req):
        if not bool(self.conf.get("enabled", False)):
            return
        if event.get_platform_name() == "webchat":
            return
        if not bool(self.conf.get("merge_history", True)):
            return
        contexts = getattr(req, "contexts", None)
        if isinstance(contexts, list):
            merged = merge_contexts(
                contexts,
                same_sender_only=not event.is_private_chat(),
                allow_labeled_cross_sender=not event.is_private_chat(),
            )
            if len(merged) < len(contexts):
                logger.info(
                    f"[{NAME}] 历史合并 user 消息 {len(contexts)} → {len(merged)}"
                )
            req.contexts = merged

    @filter.on_decorating_result()
    async def emit_face_markers(self, event: AstrMessageEvent):
        """把回复里的 [表情:名] 标记转成真的 QQ 表情，她说发就真能发出来。"""
        if not bool(self.conf.get("face_markers_enabled", True)):
            return
        if event.get_platform_name() != "aiocqhttp":
            return
        result = event.get_result()
        if result is None or not getattr(result, "chain", None):
            return
        chain = list(result.chain)
        new_chain: list = []
        changed = False
        for comp in chain:
            if (
                isinstance(comp, Plain)
                and "[表情" in str(getattr(comp, "text", ""))
            ):
                pieces = split_face_markers(getattr(comp, "text", ""))
                if any(fid is not None for _, fid in pieces):
                    for text_part, fid in pieces:
                        if text_part:
                            new_chain.append(Plain(text_part))
                        if fid is not None:
                            new_chain.append(Face(id=fid))
                    changed = True
                    continue
            new_chain.append(comp)
        if changed:
            result.chain = new_chain

    async def terminate(self) -> None:
        """插件被禁用/重载时，把还没到时间的 burst 立刻放行，别吞消息。"""
        for key in list(self._bursts):
            try:
                await self._flush(key)
            except Exception as exc:
                logger.warning(f"[{NAME}] 退出时放行消息失败：{exc}")
