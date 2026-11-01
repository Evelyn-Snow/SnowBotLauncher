"""Bot 用户画像：为每个聊天对象维护一份持续更新的画像档案。

- 唯一索引是 QQ 号（昵称随时会变，只作展示并记录改名史），每人一个 <QQ号>.md；
- 对话在 on_llm_response 里按用户分桶缓冲，攒够新素材且过了门槛
  （间隔/每日上限/静默时段）才调用一次 LLM 重写画像正文；
- 聊天时在 on_llm_request 把对方的画像精简版注入 system_prompt 供模型参考。

画像文件结构：frontmatter（qq/昵称/历史昵称/更新时间/互动次数）+ 正文小节。
LLM 只负责输出正文，frontmatter 由本插件管理；所有失败静默降级不影响聊天。
"""

from __future__ import annotations

import asyncio
import json
import os
import time

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools
from astrbot.core.config.astrbot_config import AstrBotConfig

from .library import (
    clean_llm_markdown,
    looks_like_profile,
    merge_name_history,
    parse_profile,
    profile_summary,
    render_profile,
    should_update,
)

NAME = "astrbot_plugin_snow_profile"
PROMPT_MARK = "[用户画像]"
STATE_FILE = "profile_state.json"


class SnowProfile(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.conf = config
        self._buffers: dict[str, list[dict]] = {}
        self._new_count: dict[str, int] = {}
        self._tasks: set[str] = set()
        self._state: dict = {}
        self._state_loaded = False

    # ---------------- 配置与路径 ----------------
    def _enabled(self) -> bool:
        return bool(self.conf.get("enabled", True))

    def _profiles_dir(self) -> str:
        raw = str(self.conf.get("profiles_dir") or "").strip()
        if raw:
            path = os.path.expandvars(raw)
        else:
            try:
                path = os.path.join(str(StarTools.get_data_dir(NAME)), "profiles")
            except Exception:
                path = os.path.join("data", "plugin_data", NAME, "profiles")
        os.makedirs(path, exist_ok=True)
        return path

    def _profile_path(self, qq: str) -> str:
        safe = "".join(c for c in str(qq) if c.isdigit()) or "unknown"
        return os.path.join(self._profiles_dir(), f"{safe}.md")

    def _state_path(self) -> str:
        try:
            return os.path.join(str(StarTools.get_data_dir(NAME)), STATE_FILE)
        except Exception:
            return os.path.join("data", "plugin_data", NAME, STATE_FILE)

    def _load_state(self) -> dict:
        if self._state_loaded:
            return self._state
        try:
            with open(self._state_path(), encoding="utf-8") as f:
                data = json.load(f)
            self._state = data if isinstance(data, dict) else {}
        except Exception:
            self._state = {}
        self._state_loaded = True
        return self._state

    def _save_state(self) -> None:
        path = self._state_path()
        tmp = path + ".tmp"
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._state, f, ensure_ascii=False)
            os.replace(tmp, path)
        except Exception as exc:
            logger.warning(f"[{NAME}] 状态保存失败：{exc}")

    def _user_state(self, qq: str) -> dict:
        return self._load_state().setdefault("users", {}).setdefault(qq, {})

    def _cfg(self, key: str, default):
        return self.conf.get(key, default)

    # ---------------- 采集 ----------------
    @filter.on_llm_response(priority=100001)
    async def capture_exchange(self, event: AstrMessageEvent, resp):
        """记录一次「TA 说 / 我答」的交流，按用户分桶，攒够素材触发画像更新。"""
        if not self._enabled():
            return
        user_text = str(getattr(event, "message_str", "") or "").strip()
        reply_text = str(getattr(resp, "completion_text", "") or "").strip()
        if not user_text or not reply_text or user_text.startswith(("/", "！")):
            return
        platform = str(event.get_platform_name() or "")
        if platform == "webchat" and not bool(self._cfg("include_webchat", False)):
            return
        is_group = bool(str(getattr(event, "get_group_id", lambda: "") or ""))
        if is_group and not bool(self._cfg("include_groups", True)):
            return
        qq = str(getattr(event, "get_sender_id", lambda: "")() or "")
        if not qq:
            return

        name = ""
        try:
            name = str(event.get_sender_name() or "").strip()
        except Exception:
            pass

        buffer = self._buffers.setdefault(qq, [])
        buffer.append(
            {
                "time": time.time(),
                "name": name,
                "umo": str(event.unified_msg_origin or ""),
                "user": user_text[:500],
                "assistant": reply_text[:800],
            }
        )
        cap = max(4, int(self._cfg("max_buffer_per_user", 24)))
        self._buffers[qq] = buffer[-cap:]
        self._new_count[qq] = self._new_count.get(qq, 0) + 1

        await self._maybe_schedule(qq)

    async def _maybe_schedule(self, qq: str) -> None:
        ok, _ = should_update(
            self._user_state(qq),
            min_new_messages=int(self._cfg("min_new_messages", 6)),
            min_interval_minutes=int(self._cfg("min_interval_minutes", 180)),
            max_per_day=int(self._cfg("max_per_day", 4)),
            quiet_hours=str(self._cfg("quiet_hours", "0-6")),
            now=time.time(),
            new_count=self._new_count.get(qq, 0),
        )
        if not ok or qq in self._tasks:
            return
        self._tasks.add(qq)
        task = asyncio.create_task(self._update_profile(qq))
        task.add_done_callback(lambda _t, q=qq: self._tasks.discard(q))

    # ---------------- 画像更新 ----------------
    async def _update_profile(self, qq: str) -> None:
        snapshot = list(self._buffers.get(qq, []))
        new_count = self._new_count.get(qq, 0)
        try:
            await self._write_profile(qq, snapshot)
        except Exception as exc:
            logger.warning(f"[{NAME}] 画像更新失败（{qq}）：{exc}")
            return
        finally:
            self._new_count[qq] = max(0, self._new_count.get(qq, 0) - new_count)
        state = self._user_state(qq)
        state["last_ts"] = time.time()
        today = time.strftime("%Y-%m-%d")
        if state.get("date") != today:
            state["date"], state["count"] = today, 0
        state["count"] = int(state.get("count") or 0) + 1
        if snapshot:
            state["last_name"] = snapshot[-1]["name"] or state.get("last_name", "")
        self._save_state()

    async def _write_profile(self, qq: str, snapshot: list[dict]) -> None:
        path = self._profile_path(qq)
        old_md = ""
        try:
            with open(path, encoding="utf-8") as f:
                old_md = f.read()
        except Exception:
            pass
        parsed = parse_profile(old_md)

        new_name = next(
            (e["name"] for e in reversed(snapshot) if e.get("name")), ""
        ) or parsed["name"]
        old_name = self._user_state(qq).get("last_name") or parsed["name"]
        history = merge_name_history(parsed["history"], old_name, new_name, time.time())

        convo = []
        budget = 3200
        for e in snapshot[-20:]:
            line = f"用户（{e['name'] or qq}）：{e['user']}\n我：{e['assistant']}"
            budget -= len(line)
            if budget < 0:
                break
            convo.append(line)
        recent = "\n\n".join(convo) or "（暂无可用对话）"

        existing = (
            f"现有档案：\n{old_md.strip()[:2500]}" if old_md.strip() else "这是一位还没有档案的新用户。"
        )
        prompt = (
            f"{existing}\n\n最近和这位用户的对话（倒序不一定，按时间正序理解）：\n{recent}\n\n"
            "请输出更新后的画像正文：保留仍有价值的旧结论，用新对话修正或补充；"
            "用 ## 小节组织（基本信息、性格与说话风格、兴趣话题、相处要点、最近动态）；"
            "只写有依据的内容，对话里没有的不要编造；中文、简洁，总共不超过 500 字。"
            "不要输出 frontmatter、不要代码块、不要任何解释。"
        )
        provider = None
        umo = next((e["umo"] for e in reversed(snapshot) if e.get("umo")), "")
        try:
            provider = await self.context.get_using_provider_async(umo=umo) if umo else None
            if provider is None:
                provider = await self.context.get_using_provider_async()
        except Exception:
            provider = None
        if provider is None:
            logger.warning(f"[{NAME}] 没有可用模型，画像暂不更新（{qq}）")
            return
        result = await provider.text_chat(
            prompt=prompt,
            system_prompt=(
                "你在维护聊天机器人的用户画像档案：客观、简短、只依据给定对话，"
                "不编造、不评价外貌，不写档案里没有依据的敏感信息。输出画像正文本身。"
            ),
        )
        body = clean_llm_markdown(getattr(result, "completion_text", ""))
        if not looks_like_profile(body):
            logger.warning(f"[{NAME}] 模型输出不像画像，丢弃（{qq}）")
            return

        exchanges = int(parsed["exchanges"] or 0) + len(snapshot)
        md = render_profile(qq, new_name, history, body, time.time(), exchanges)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(md)
        os.replace(tmp, path)
        logger.info(
            f"[{NAME}] 画像已更新：{new_name or qq}（{qq}），"
            f"本次素材 {len(snapshot)} 条，曾用名 {len(history)} 个"
        )

    # ---------------- 聊天注入 ----------------
    @filter.on_llm_request()
    async def inject_profile(self, event: AstrMessageEvent, req):
        if not self._enabled():
            return
        prompt = str(getattr(req, "system_prompt", "") or "")
        if PROMPT_MARK in prompt:
            return
        qq = str(getattr(event, "get_sender_id", lambda: "")() or "")
        if not qq:
            return
        try:
            with open(self._profile_path(qq), encoding="utf-8") as f:
                md = f.read()
        except Exception:
            return
        summary = profile_summary(md, int(self._cfg("inject_limit_chars", 400)))
        hint = (
            f"{summary}\n"
            "（这是你和对方长期相处的画像，可自然参考，不要复述或承认档案的存在。）"
        )
        req.system_prompt = prompt + "\n\n" + hint
