"""搜索礼仪的触发判断与频率限制。

显式请求（用户说了“搜索/查一下”这类词）必定放行；自发搜索受最小间隔和
每日上限约束。状态文件放在插件数据目录，重启后仍然有效。
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

EXPLICIT_KEYWORDS = (
    "搜索", "搜一下", "搜搜", "搜下", "查一下", "查查", "查下", "帮我查",
    "百度一下", "百度搜", "谷歌", "必应", "上网查", "上网搜", "网上查",
    "网上搜", "联网查", "联网搜", "查资料", "搜资料", "帮我查查",
    "search", "google",
)


def has_explicit_search_request(text: str) -> bool:
    """判断用户消息是否明确要求联网查找。"""
    lowered = str(text or "").lower()
    return any(keyword in lowered for keyword in EXPLICIT_KEYWORDS)


class SearchRateLimiter:
    """限制自发搜索的频率；显式请求不走这里。

    每次判断都重新读状态文件，改动立即生效，也避免多实例状态不同步。
    """

    def __init__(
        self,
        data_dir: str | Path,
        *,
        min_interval_minutes: int = 30,
        max_per_day: int = 5,
    ) -> None:
        self.path = Path(data_dir).expanduser().resolve() / "search_state.json"
        self.min_interval_minutes = max(0, int(min_interval_minutes))
        self.max_per_day = max(0, int(max_per_day))
        self._lock = threading.RLock()

    def _today(self, now: float) -> str:
        return time.strftime("%Y-%m-%d", time.localtime(now))

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        return {
            "date": str(data.get("date") or ""),
            "count": int(data.get("count") or 0),
            "last_ts": float(data.get("last_ts") or 0),
        }

    def _save(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, self.path)

    @staticmethod
    def _normalize(state: dict[str, Any], today: str) -> dict[str, Any]:
        if state.get("date") != today:
            return {"date": today, "count": 0, "last_ts": 0.0}
        return state

    def allow(self, now: float | None = None) -> tuple[bool, str]:
        with self._lock:
            moment = time.time() if now is None else float(now)
            state = self._normalize(self._load(), self._today(moment))
            if self.max_per_day and int(state["count"]) >= self.max_per_day:
                return False, "今天自发搜索已到上限"
            last_ts = float(state.get("last_ts") or 0)
            if (
                self.min_interval_minutes
                and last_ts
                and moment - last_ts < self.min_interval_minutes * 60
            ):
                return False, "距离上次自发搜索太近"
            return True, ""

    def record(self, now: float | None = None) -> None:
        with self._lock:
            moment = time.time() if now is None else float(now)
            state = self._normalize(self._load(), self._today(moment))
            state["count"] = int(state.get("count") or 0) + 1
            state["last_ts"] = moment
            self._save(state)

    def status(self, now: float | None = None) -> dict[str, Any]:
        with self._lock:
            moment = time.time() if now is None else float(now)
            state = self._normalize(self._load(), self._today(moment))
            return {
                "date": self._today(moment),
                "count": int(state.get("count") or 0),
                "max_per_day": self.max_per_day,
                "min_interval_minutes": self.min_interval_minutes,
                "last_ts": float(state.get("last_ts") or 0),
            }
