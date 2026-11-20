"""像个人：让她按语境决定回多长，并把一条回复拆成自然的气泡。

不改造人格，也不改 AstrBot 源码。两处介入：

- on_llm_request：这轮是短回、先安慰、正经回答还是普通聊天，往系统提示最后
  补一句“怎么回”；群聊里没被点名、又只是“哈哈/嗯”的低信息消息，按概率不接。
- on_decorating_result：模型回复先按句子分组，再交给 AstrBot 自带的分段回复
  逐条发送；每个气泡内部只留最后一个句末标点，避免被二次切碎。

状态只记录每个会话最近的回复长度和“精力”，用来打破连续长篇的机械感。
"""

from __future__ import annotations

import json
import os
import random
import threading
import time
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import At, Plain
from astrbot.api.star import Context, Star, StarTools
from astrbot.core.config.astrbot_config import AstrBotConfig

from .library import (
    END_MARK,
    STYLE_MARK,
    choose_mode,
    is_low_content,
    shape_text,
    style_hint,
    update_state,
)

NAME = "astrbot_plugin_snow_humanize"
STATE_FILE = "humanize_state.json"
PREPARED_EXTRA = "_snow_humanize_prepared"
MODE_EXTRA = "_snow_humanize_mode"
SHAPED_EXTRA = "_snow_humanize_shaped"


class SnowHumanize(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.conf = config
        self._state: dict = {"version": 1, "sessions": {}}
        self._loaded = False
        self._lock = threading.RLock()
        self._last_save = 0.0
        self._rng = random.Random()

    # ---------------- 基础 ----------------
    def _enabled(self) -> bool:
        return bool(self.conf.get("enabled", True))

    def _cfg(self, key: str, default):
        return self.conf.get(key, default)

    def _platform_enabled(self, event: AstrMessageEvent) -> bool:
        raw = str(self._cfg("enabled_platforms", "aiocqhttp,webchat") or "")
        names = {
            item.strip()
            for item in raw.replace("，", ",").split(",")
            if item.strip()
        }
        return not names or event.get_platform_name() in names

    def _data_dir(self) -> Path:
        try:
            return Path(str(StarTools.get_data_dir(NAME)))
        except Exception:
            path = Path("data") / "plugin_data" / NAME
            path.mkdir(parents=True, exist_ok=True)
            return path

    def _load_state(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            path = self._data_dir() / STATE_FILE
            try:
                with open(path, encoding="utf-8") as handle:
                    data = json.load(handle)
                sessions = data.get("sessions") if isinstance(data, dict) else None
                if isinstance(sessions, dict):
                    self._state["sessions"] = sessions
            except Exception:
                self._state["sessions"] = {}
            self._prune_sessions()
            self._loaded = True

    def _prune_sessions(self) -> None:
        try:
            ttl = max(1.0, float(self._cfg("state_ttl_days", 7))) * 86400
        except (TypeError, ValueError):
            ttl = 7 * 86400
        now = time.time()
        sessions = self._state.get("sessions") or {}
        dead = [
            key
            for key, value in sessions.items()
            if not isinstance(value, dict)
            or now - float(value.get("updated") or 0) > ttl
        ]
        for key in dead:
            sessions.pop(key, None)
        if len(sessions) > 300:
            ordered = sorted(
                sessions.items(),
                key=lambda item: float((item[1] or {}).get("updated") or 0),
            )
            for key, _ in ordered[: len(sessions) - 300]:
                sessions.pop(key, None)

    def _save_state(self, force: bool = False) -> None:
        with self._lock:
            now = time.monotonic()
            if not force and now - self._last_save < 5.0:
                return
            path = self._data_dir() / STATE_FILE
            tmp = path.with_name(
                f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
            )
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(tmp, "w", encoding="utf-8") as handle:
                    json.dump(self._state, handle, ensure_ascii=False, indent=1)
                os.replace(tmp, path)
                self._last_save = now
            except Exception as exc:
                logger.warning(f"[{NAME}] 状态保存失败：{exc}")

    def _session_state(self, umo: str) -> dict:
        self._load_state()
        sessions = self._state.setdefault("sessions", {})
        value = sessions.get(umo)
        if not isinstance(value, dict):
            value = {}
            sessions[umo] = value
        return value

    def _segment_config(self) -> tuple[bool, int]:
        try:
            config = self.context.get_config()
            settings = (config.get("platform_settings") or {}).get(
                "segmented_reply"
            ) or {}
            enabled = bool(settings.get("enable", True))
            threshold = int(settings.get("words_count_threshold", 80))
            return enabled, threshold
        except Exception:
            return True, 80

    # ---------------- 这轮怎么回 ----------------
    def _addressed(self, event: AstrMessageEvent) -> bool:
        if bool(getattr(event, "is_at_or_wake_command", False)):
            return True
        try:
            if event.is_wake_up():
                return True
        except Exception:
            pass
        self_id = str(getattr(event, "get_self_id", lambda: "")() or "")
        if not self_id:
            return False
        try:
            components = getattr(event.message_obj, "message", None) or []
        except Exception:
            components = []
        return any(
            isinstance(component, At) and str(getattr(component, "qq", "")) == self_id
            for component in components
        )

    @filter.on_llm_request(priority=-(1 << 30) - 100)
    async def hint_reply_style(self, event: AstrMessageEvent, req):
        if not self._enabled() or not self._platform_enabled(event):
            return
        if event.get_extra(PREPARED_EXTRA):
            return
        text = str(getattr(event, "message_str", "") or "")
        umo = str(event.unified_msg_origin or "")
        private = event.is_private_chat()
        addressed = self._addressed(event)
        state = self._session_state(umo) if umo else {}
        mode = choose_mode(
            text,
            is_group=not private,
            addressed=addressed,
            state=state,
            rng=self._rng,
        )
        event.set_extra(PREPARED_EXTRA, True)
        event.set_extra(MODE_EXTRA, mode)

        # 群聊里没被点名，又只是“哈哈/嗯/好”这种低信息消息：偶尔不接，别像复读机。
        if (
            mode == "short"
            and not private
            and not addressed
            and is_low_content(text)
            and bool(self._cfg("group_skip_low_content", True))
        ):
            try:
                chance = float(self._cfg("group_skip_chance", 0.55))
            except (TypeError, ValueError):
                chance = 0.55
            if self._rng.random() < max(0.0, min(1.0, chance)):
                logger.info(f"[{NAME}] 群聊低信息消息，这轮不接：{text[:30]!r}")
                event.stop_event()
                return

        try:
            prompt = str(getattr(req, "system_prompt", "") or "")
        except Exception:
            prompt = ""
        if STYLE_MARK not in prompt:
            hint = style_hint(mode, state, self._rng)
            req.system_prompt = (prompt + "\n\n" + hint) if prompt else hint
        logger.debug(f"[{NAME}] 这轮按 {mode} 回：{text[:40]!r}")

    # ---------------- 把回复拆成气泡 ----------------
    @filter.on_decorating_result(priority=-1500)
    async def shape_reply(self, event: AstrMessageEvent):
        if not self._enabled() or not self._platform_enabled(event):
            return
        if event.get_extra(SHAPED_EXTRA):
            return
        result = event.get_result()
        if result is None or not getattr(result, "chain", None):
            return
        try:
            if not result.is_llm_result():
                return
        except Exception:
            return
        chain = list(result.chain)
        plain_indices = [
            index for index, component in enumerate(chain) if isinstance(component, Plain)
        ]
        if not plain_indices:
            return
        first, last = plain_indices[0], plain_indices[-1]
        # 文字必须连在一起；文字中间夹图片/语音就不动，避免把内容顺序打乱。
        if last - first + 1 != len(plain_indices):
            return
        text = "\n".join(str(chain[index].text or "") for index in plain_indices).strip()
        if not text:
            return
        if END_MARK in text:
            return

        mode = str(event.get_extra(MODE_EXTRA) or "normal")
        segment_enabled, threshold = self._segment_config()
        bubbles = shape_text(
            text,
            mode=mode,
            segment_threshold=threshold,
            allow_bubbles=segment_enabled,
            short_max_chars=int(self._cfg("short_reply_max_chars", 45) or 45),
            conf={
                "two_bubble_chance": self._cfg("two_bubble_chance", 0.35),
                "three_bubble_chance": self._cfg("three_bubble_chance", 0.1),
            },
            rng=self._rng,
        )
        if not bubbles:
            return
        new_chain = (
            chain[:first]
            + [Plain(bubble) for bubble in bubbles]
            + chain[last + 1 :]
        )
        original_texts = [
            str(component.text) for component in chain if isinstance(component, Plain)
        ]
        new_texts = [
            str(component.text) for component in new_chain if isinstance(component, Plain)
        ]
        if new_texts != original_texts:
            result.chain = new_chain
            logger.info(
                f"[{NAME}] {mode} → {len(bubbles)} 段："
                + " / ".join(bubble[:24] for bubble in bubbles)
            )
        event.set_extra(SHAPED_EXTRA, True)

        umo = str(event.unified_msg_origin or "")
        if umo:
            with self._lock:
                sessions = self._state.setdefault("sessions", {})
                sessions[umo] = update_state(
                    sessions.get(umo),
                    user_text=str(getattr(event, "message_str", "") or ""),
                    reply_text=text,
                )
            self._save_state()

    async def terminate(self) -> None:
        self._save_state(force=True)
