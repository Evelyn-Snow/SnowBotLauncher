"""小雪状态：按虚拟日程和心情，低频更新 QQ 签名与在线状态。

和虚拟人生联动：读当天时间线，知道她现在在做什么；隔几小时换一句签名，
并把在线状态切到对应的（学习中/睡觉中/追剧中/在线等）。静默时段不动。
"""

from __future__ import annotations

import asyncio
import datetime
import json
import random
import time
from pathlib import Path

from astrbot.api import logger
from astrbot.api.star import Context, Star, StarTools
from astrbot.core.config.astrbot_config import AstrBotConfig

from .library import (
    build_signature_prompt,
    clean_signature,
    fallback_signature,
    pick_status,
)

NAME = "astrbot_plugin_snow_status"
STATE_FILE = "status_state.json"

STATUS_CODES = {
    "在线": (10, 0),
    "离开": (30, 0),
    "忙碌": (50, 0),
    "睡觉中": (10, 1016),
    "学习中": (10, 1018),
    "肝作业": (10, 2012),
    "元气满满": (10, 1058),
    "追剧中": (10, 1021),
    "听歌中": (10, 1028),
    "timi中": (10, 1027),
    "摸鱼中": (10, 1300),
    "悠哉哉": (10, 1059),
    "想静静": (10, 1061),
    "出去浪": (10, 2003),
}


class SnowStatus(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.conf = config
        self._task: asyncio.Task | None = None
        self._state: dict = {}

    # ---------------- 基础 ----------------
    def _enabled(self) -> bool:
        return bool(self.conf.get("enabled", True))

    def _cfg(self, key: str, default):
        return self.conf.get(key, default)

    def _data_dir(self) -> Path:
        try:
            return Path(str(StarTools.get_data_dir(NAME)))
        except Exception:
            path = Path("data") / "plugin_data" / NAME
            path.mkdir(parents=True, exist_ok=True)
            return path

    def _load_state(self) -> dict:
        if self._state:
            return self._state
        try:
            with open(self._data_dir() / STATE_FILE, encoding="utf-8") as f:
                data = json.load(f)
            self._state = data if isinstance(data, dict) else {}
        except Exception:
            self._state = {}
        return self._state

    def _save_state(self) -> None:
        path = self._data_dir() / STATE_FILE
        tmp = path.with_suffix(".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._state, f, ensure_ascii=False, indent=1)
            tmp.replace(path)
        except Exception as exc:
            logger.warning(f"[{NAME}] 状态保存失败：{exc}")

    # ---------------- 虚拟日程 ----------------
    def _persona_name(self) -> str:
        try:
            cfg = self.context.get_config()
            agent = (cfg.get("agent_runner") or {}).get("config") or {}
            return str(
                (agent.get("persona") or {}).get("persona_id")
                or (cfg.get("provider_settings") or {}).get("default_personality")
                or ""
            )
        except Exception:
            return ""

    def _today_plan(self) -> dict:
        path = self._data_dir().parent / "astrbot_plugin_virtual_life" / "plans.json"
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return {}
        plans = data.get("plans") if isinstance(data, dict) else None
        if not isinstance(plans, dict):
            return {}
        today = datetime.date.today().isoformat()
        persona = self._persona_name()
        hits = [
            value
            for key, value in plans.items()
            if isinstance(value, dict) and str(key).startswith(f"{today}::")
        ]
        for plan in hits:
            if str(plan.get("persona_id", "")) == persona:
                return plan
        return hits[0] if len(hits) == 1 else {}

    def _current_activity(self) -> tuple[str, str, str]:
        """返回 (活动, 地点, 状态)；没有日程时返回空。"""
        plan = self._today_plan()
        timeline = plan.get("timeline") or []
        now = datetime.datetime.now().strftime("%H:%M")
        for item in timeline:
            if not isinstance(item, dict):
                continue
            start = str(item.get("start") or "")
            end = str(item.get("end") or "")
            if start <= now < end or (end == "24:00" and now >= start):
                return (
                    str(item.get("activity") or ""),
                    str(item.get("place") or ""),
                    str(item.get("state") or ""),
                )
        return "", "", ""

    # ---------------- QQ 操作 ----------------
    def _bot_and_self_id(self):
        try:
            platform = self.context.get_platform("aiocqhttp")
        except Exception:
            platform = None
        if platform is None:
            try:
                for candidate in self.context.platform_manager.platform_insts:
                    if getattr(candidate.meta(), "name", "") == "aiocqhttp":
                        platform = candidate
                        break
            except Exception:
                platform = None
        bot = getattr(platform, "bot", None) if platform is not None else None
        if bot is None:
            return None, None
        self_id = None
        try:
            clients = getattr(bot, "_wsr_api_clients", None) or {}
            if isinstance(clients, dict) and clients:
                self_id = int(next(iter(clients)))
        except Exception:
            self_id = None
        return bot, self_id

    # ---------------- 生成与更新 ----------------
    async def _provider(self):
        try:
            return await self.context.get_using_provider_async()
        except Exception:
            return None

    def _recent_experience(self) -> str:
        """读真实经历插件的最新记录，让签名能呼应她刚做过的事。"""
        path = (
            self._data_dir().parent
            / "astrbot_plugin_snow_experience"
            / "experience_state.json"
        )
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            records = data.get("records") if isinstance(data, dict) else None
            if not records:
                return ""
            last = records[-1]
            if not isinstance(last, dict):
                return ""
            title = str(last.get("title") or "").strip()
            gist = str(last.get("gist") or "").strip()
            return f"{title}：{gist}"[:100].strip("：")
        except Exception:
            return ""

    async def _make_signature(self, activity: str, place: str, state: str) -> str:
        provider = await self._provider()
        if provider is None:
            return fallback_signature(int(time.time()))
        hour = datetime.datetime.now().hour
        try:
            result = await asyncio.wait_for(
                provider.text_chat(
                    prompt=build_signature_prompt(
                        activity, place, state, hour, self._recent_experience()
                    ),
                    system_prompt="你正在给自己写一句 QQ 签名，只输出这一句，不要解释。",
                ),
                timeout=30,
            )
            text = clean_signature(
                str(getattr(result, "completion_text", "") or ""),
                int(self._cfg("max_chars", 24)),
            )
            return text or fallback_signature(int(time.time()))
        except Exception as exc:
            logger.info(f"[{NAME}] 生成签名失败，用默认句：{exc}")
            return fallback_signature(int(time.time()))

    async def _update_once(self) -> None:
        if not self._enabled():
            return
        activity, place, state = self._current_activity()
        bot, self_id = self._bot_and_self_id()
        if bot is None:
            logger.info(f"[{NAME}] 没有可用的 OneBot 连接，跳过")
            return
        signature = await self._make_signature(activity, place, state)
        status_name = pick_status(activity, state)
        status_code = STATUS_CODES.get(status_name, STATUS_CODES["在线"])
        changed = []
        if bool(self._cfg("signature_enabled", True)) and signature:
            try:
                await bot.call_action(
                    "set_qq_profile", personal_note=signature, self_id=self_id
                )
                changed.append(f"签名「{signature}」")
            except Exception as exc:
                logger.warning(f"[{NAME}] 更新签名失败：{exc}")
        if bool(self._cfg("status_enabled", True)):
            try:
                await bot.call_action(
                    "set_online_status",
                    status=status_code[0],
                    ext_status=status_code[1],
                    battery_status=0,
                    self_id=self_id,
                )
                changed.append(f"状态「{status_name}」")
            except Exception as exc:
                logger.warning(f"[{NAME}] 更新状态失败：{exc}")
        state_data = self._load_state()
        state_data["last_update"] = time.time()
        state_data["last_signature"] = signature
        state_data["last_status"] = status_name
        state_data["last_activity"] = activity
        min_h = max(1.0, float(self._cfg("min_interval_hours", 4)))
        max_h = max(min_h, float(self._cfg("max_interval_hours", 8)))
        state_data["next_update"] = time.time() + random.uniform(min_h, max_h) * 3600
        self._save_state()
        if changed:
            logger.info(f"[{NAME}] 已更新{'、'.join(changed)}（{activity or '无日程'}）")

    def _in_quiet_hours(self) -> bool:
        spec = str(self._cfg("quiet_hours", "23-8"))
        try:
            start, end = [int(part) for part in spec.split("-", 1)]
        except Exception:
            return False
        hour = datetime.datetime.now().hour
        return hour >= start or hour < end if start > end else start <= hour < end

    async def _loop(self) -> None:
        while True:
            try:
                if not self._in_quiet_hours():
                    state = self._load_state()
                    now = time.time()
                    if now >= float(state.get("next_update") or 0):
                        await self._update_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(f"[{NAME}] 状态轮询失败：{exc}")
            await asyncio.sleep(600)

    async def initialize(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def terminate(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
