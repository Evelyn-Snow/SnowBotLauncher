"""小雪引用回复：由她自己判断要不要引用，并搜索前文找到该回哪一句。

不是每条都引用，也不是用户下命令才引用：
- 每个进入会话的消息先记进本地小历史（带 QQ 消息 id）
- 模型觉得“话题乱了 / 对方同时说了几件事 / 要回的那句在很前面”时，
  调用 quote_reply(target=原话片段或描述) 搜索前文
- 搜索只接受距离足够远（消息条数或时间）的目标；太近会拒绝
- 命中后在回复前加 Reply；每个会话有冷却、每小时/每天上限
"""

from __future__ import annotations

import json
import os
import threading
import time

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Reply
from astrbot.api.star import Context, Star, StarTools
from astrbot.core.config.astrbot_config import AstrBotConfig

from .library import format_record, search_quote_target

NAME = "astrbot_plugin_snow_reply"
PROMPT_MARK = "[引用回复]"
_SAVE_INTERVAL = 5.0


class SnowReply(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.conf = config
        self._pending: dict[tuple[str, str], dict] = {}
        self._cooldowns: dict[str, list[float]] = {}
        self._history: dict[str, list[dict]] = {}
        self._history_dirty = False
        self._history_lock = threading.RLock()
        self._last_save = 0.0
        self._load_history()

    # ---------------- 配置/存储 ----------------
    def _enabled(self) -> bool:
        return bool(self.conf.get("enabled", True))

    def _data_dir(self) -> str:
        try:
            return str(StarTools.get_data_dir(NAME))
        except Exception:
            return os.path.join("data", "plugin_data", NAME)

    def _history_path(self) -> str:
        return os.path.join(self._data_dir(), "quote_history.json")

    def _load_history(self) -> None:
        try:
            with open(self._history_path(), encoding="utf-8") as f:
                data = json.load(f)
            self._history = data if isinstance(data, dict) else {}
        except Exception:
            self._history = {}
        for key, rows in list(self._history.items()):
            if not isinstance(rows, list):
                self._history[key] = []

    def _save_history(self, force: bool = False) -> None:
        if not self._history_dirty:
            return
        now = time.monotonic()
        if not force and now - self._last_save < _SAVE_INTERVAL:
            return
        path = self._history_path()
        with self._history_lock:
            tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self._history, f, ensure_ascii=False)
                os.replace(tmp, path)
                self._history_dirty = False
                self._last_save = now
            except Exception as exc:
                logger.warning(f"[{NAME}] 引用历史保存失败：{exc}")

    def _cap(self) -> int:
        return max(20, int(self.conf.get("history_per_session") or 300))

    # ---------------- 记录前文 ----------------
    @staticmethod
    def _placeholder(components) -> str:
        for comp in components or []:
            name = comp.__class__.__name__.lower()
            if name == "record":
                return "[语音]"
            if name == "video":
                return "[视频]"
            if name == "image":
                return "[图片]"
            if name == "file":
                return f"[文件] {getattr(comp, 'name', '')}".strip()
            if name == "json":
                return "[卡片]"
        return ""

    @filter.event_message_type(
        filter.EventMessageType.ALL, priority=(1 << 31) + 10
    )
    async def record_message(self, event: AstrMessageEvent):
        """在合流/媒体处理之前记录每条原始消息，保留 QQ message_id。"""
        if not self._enabled():
            return
        if event.get_extra("_snow_burst_merged"):
            return
        text = str(event.message_str or "").strip()
        if text.startswith(("/", "！", "!")):
            return
        components = getattr(event.message_obj, "message", None) or []
        if not text:
            text = self._placeholder(components)
        if not text:
            return
        umo = str(event.unified_msg_origin or "")
        message_id = str(getattr(event.message_obj, "message_id", "") or "")
        if not umo or not message_id:
            return
        rows = self._history.setdefault(umo, [])
        if rows and str(rows[-1].get("id") or "") == message_id:
            return
        rows.append(
            {
                "id": message_id,
                "sender_id": str(event.get_sender_id() or ""),
                "sender_name": str(event.get_sender_name() or ""),
                "text": text[:300],
                "ts": time.time(),
            }
        )
        if len(rows) > self._cap():
            del rows[: -self._cap()]
        if len(self._history) > 30:
            # 保留最近有活动的 30 个会话
            for key in list(self._history)[:-30]:
                self._history.pop(key, None)
        self._history_dirty = True
        self._save_history()

    # ---------------- 模型工具 ----------------
    @staticmethod
    def _quoted_record(event: AstrMessageEvent) -> dict | None:
        """把用户这次带上的引用也作为候选，支持引用插件启动前的旧消息。"""
        for comp in getattr(event.message_obj, "message", None) or []:
            if comp.__class__.__name__.lower() != "reply":
                continue
            text = str(getattr(comp, "message_str", "") or "").strip()
            if not text:
                return None
            try:
                ts = float(getattr(comp, "time", 0) or 0)
            except (TypeError, ValueError):
                ts = 0.0
            return {
                "id": str(getattr(comp, "id", "") or ""),
                "sender_id": str(getattr(comp, "sender_id", "") or ""),
                "sender_name": str(getattr(comp, "sender_nickname", "") or ""),
                "text": text[:300],
                "ts": ts,
            }
        return None

    def _cooldown_ok(self, umo: str) -> tuple[bool, str]:
        now = time.time()
        rows = [t for t in self._cooldowns.get(umo, []) if now - t < 86400]
        self._cooldowns[umo] = rows
        if rows and now - rows[-1] < max(1, int(self.conf.get("cooldown_minutes") or 30)) * 60:
            return False, "刚刚已经引用过一条了"
        if len([t for t in rows if now - t < 3600]) >= max(
            1, int(self.conf.get("max_per_hour") or 2)
        ):
            return False, "这个小时引用次数已满"
        if len(rows) >= max(1, int(self.conf.get("max_per_day") or 6)):
            return False, "今天引用次数已满"
        return True, ""

    @filter.llm_tool(name="quote_reply")
    async def quote_reply(
        self,
        event: AstrMessageEvent,
        target: str,
        reason: str = "",
    ) -> str:
        """在当前会话的前文里搜索一条消息，并准备用引用回复它。

        只在当前话题混乱、对方同时说了几件事、或你要回的那句在很前面、
        直接说会指代不清时使用；普通聊天不要调用，不要每轮都用。

        Args:
            target(string): 目标消息的原话片段、关键词或明确描述
            reason(string): 为什么需要引用，可留空
        """
        if not self._enabled():
            return "引用回复未启用，直接正常回答。"
        umo = str(event.unified_msg_origin or "")
        if not umo:
            return "无法确定会话，直接正常回答。"
        ok, why = self._cooldown_ok(umo)
        if not ok:
            return f"{why}；这次不要引用，直接正常回答。"
        current_id = str(getattr(event.message_obj, "message_id", "") or "")
        now = time.time()
        records = list(self._history.get(umo, []))
        quoted = self._quoted_record(event)
        if quoted and quoted.get("id"):
            current_index = len(records)
            for index in range(len(records) - 1, -1, -1):
                if str(records[index].get("id") or "") == current_id:
                    current_index = index
                    break
            records.insert(current_index, quoted)
        record, detail = search_quote_target(
            records,
            target,
            current_id,
            now=now,
            lookback_minutes=int(self.conf.get("lookback_minutes") or 720),
            lookback_messages=int(self.conf.get("lookback_messages") or 200),
            min_message_distance=int(self.conf.get("min_message_distance") or 4),
            min_time_distance_minutes=int(
                self.conf.get("min_time_distance_minutes") or 10
            ),
            threshold=float(self.conf.get("search_threshold") or 0.2),
        )
        if record is None:
            return f"{detail}。这次不要强行引用，直接回答。"
        self._pending[(umo, current_id)] = {
            "record": record,
            "event_id": current_id,
            "expires": time.time() + max(
                30, int(self.conf.get("intent_ttl_seconds") or 300)
            ),
        }
        logger.info(
            f"[{NAME}] 模型决定引用：{format_record(record)}"
            f"（{detail}；原因：{reason or '未说明'}）"
        )
        return (
            f"已找到要引用的消息：{format_record(record)}\n"
            f"（{detail}）正常回答即可，系统会自动在消息前加引用；"
            "不要提“引用”“回复功能”这些词。"
        )

    @filter.on_llm_request()
    async def hint_quote(self, event: AstrMessageEvent, req):
        if not self._enabled():
            return
        prompt = str(getattr(req, "system_prompt", "") or "")
        if PROMPT_MARK in prompt:
            return
        req.system_prompt = prompt + (
            "\n\n[引用回复] 只有当前话题混乱、对方同时说了几件事，"
            "或你要回的那句在很前面、直接说会指代不清时，才调用 quote_reply "
            "搜索前文并引用；普通聊天不要引用，不要频繁用。"
        )

    # ---------------- 发出前加引用 ----------------
    def _take(self, umo: str, event_id: str) -> dict | None:
        key = (umo, str(event_id or ""))
        item = self._pending.get(key)
        if not item:
            return None
        if time.time() > float(item.get("expires") or 0):
            self._pending.pop(key, None)
            return None
        self._pending.pop(key, None)
        return item

    @filter.on_decorating_result(priority=-1000)
    async def add_quote(self, event: AstrMessageEvent):
        if not self._enabled():
            return
        umo = str(event.unified_msg_origin or "")
        event_id = str(getattr(event.message_obj, "message_id", "") or "")
        item = self._take(umo, event_id)
        if item is None:
            return
        result = event.get_result()
        if result is None or not getattr(result, "chain", None):
            return
        if any(isinstance(comp, Reply) for comp in result.chain):
            return
        record = item.get("record") or {}
        reply = Reply(
            id=record.get("id"),
            sender_id=record.get("sender_id"),
            sender_nickname=record.get("sender_name") or "",
            time=int(record.get("ts") or 0),
            message_str=record.get("text") or "",
        )
        if not isinstance(result.chain, list):
            result.chain = list(result.chain)
        result.chain.insert(0, reply)
        now = time.time()
        rows = [t for t in self._cooldowns.get(umo, []) if now - t < 86400]
        rows.append(now)
        self._cooldowns[umo] = rows
        logger.info(f"[{NAME}] 已在回复前加上引用：{record.get('id')}")

    async def terminate(self) -> None:
        self._pending.clear()
        self._history_dirty = True
        self._save_history(force=True)
