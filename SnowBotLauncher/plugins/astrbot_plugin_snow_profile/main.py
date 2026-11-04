"""Bot 印象笔记：为每个聊天对象维护一份持续更新的印象笔记。

- 唯一索引是 QQ 号（昵称随时会变，只作展示并记录改名史），每人一个 <QQ号>.md；
- 正文由她自己用第一人称、按平时聊天的口吻写（不是客观档案），聊天时注入后
  就像她自己的记忆；
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
import random
import threading
import time
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import At, Plain
from astrbot.api.star import Context, Star, StarTools
from astrbot.core.config.astrbot_config import AstrBotConfig

from .library import (
    PROFILE_SYSTEM_PROMPT,
    SUMMARY_MARK,
    apply_moral_delta,
    build_moral_section,
    build_profile_prompt,
    clean_llm_markdown,
    compute_familiarity,
    current_timeline_item,
    activity_allows_proactive,
    activity_line,
    extract_impression,
    extract_score,
    familiarity_guidance,
    in_quiet_hours,
    in_time_windows,
    looks_like_profile,
    merge_name_history,
    moral_injection,
    moral_level,
    moral_section,
    parse_profile,
    pick_today_plan,
    profile_summary,
    render_profile,
    should_ignore,
    should_update,
    smooth_score,
    split_moral_section,
    strip_impression,
)

NAME = "astrbot_plugin_snow_profile"
PROMPT_MARK = SUMMARY_MARK
STATE_FILE = "profile_state.json"


class SnowProfile(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.conf = config
        self._buffers: dict[str, list[dict]] = {}
        self._new_count: dict[str, int] = {}
        self._tasks: set[str] = set()
        self._profile_tasks: set[asyncio.Task] = set()
        self._state: dict = {}
        self._state_loaded = False
        self._state_lock = threading.RLock()
        self._score_cache: dict[str, tuple[float, int | None]] = {}
        self._history_locks: dict[str, asyncio.Lock] = {}
        self._proactive_task: asyncio.Task | None = None

    async def initialize(self) -> None:
        if bool(self.conf.get("proactive_enabled", False)):
            self._proactive_task = asyncio.create_task(self._proactive_loop())

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
        with self._state_lock:
            tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
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

    # ---------------- 熟悉度 ----------------
    def _is_admin_qq(self, qq: str) -> bool:
        try:
            owner = str(self._cfg("owner_session", "") or "").strip()
            if owner and owner.rsplit(":", 1)[-1] == str(qq):
                return True
        except Exception:
            pass
        try:
            admins = self.context.get_config().get("admins_id") or []
            return str(qq) in {str(a) for a in admins}
        except Exception:
            return False

    def _bump_activity(self, qq: str, umo: str, name: str) -> None:
        """记录聊天频率、活跃天数和最近一次出现的会话。"""
        state = self._user_state(qq)
        now = time.time()
        state["total_messages"] = int(state.get("total_messages") or 0) + 1
        state["last_seen_ts"] = now
        state["last_umo"] = umo
        if ":FriendMessage:" in umo and not umo.startswith("webchat:"):
            state["last_private_umo"] = umo
        if name:
            state["last_name"] = name
        state.setdefault("first_ts", now)
        days = state.setdefault("active_days", [])
        today = time.strftime("%Y-%m-%d", time.localtime(now))
        if today not in days:
            days.append(today)
            if len(days) > 90:
                del days[:-90]
        # 画像文件本身有更新门槛，状态文件每 10 条落一次盘即可
        if state["total_messages"] % 10 == 0:
            self._save_state()

    def _familiarity_of(
        self, qq: str, md: str, is_webchat: bool = False
    ) -> tuple[int, str, int, int, int, int]:
        """返回 (熟悉度, 等级, 互动次数, 活跃天数, 印象分, 道德分)。"""
        parsed = parse_profile(md)
        state = self._user_state(qq)
        exchanges = max(
            int(parsed.get("exchanges") or 0),
            int(state.get("total_messages") or 0),
        )
        active_days = (
            len(state.get("active_days") or [])
            or int(parsed.get("active_days") or 0)
        )
        impression = parsed.get("impression_score")
        if impression is None:
            impression = int(self._cfg("impression_initial", 50))
        moral = parsed.get("moral_score")
        if moral is None:
            moral = extract_score(md, int(self._cfg("moral_initial", 75)))
        last_seen = float(state.get("last_seen_ts") or 0)
        days_since = (time.time() - last_seen) / 86400 if last_seen else 0.0
        score, level = compute_familiarity(
            exchanges,
            active_days,
            impression,
            moral if moral is not None else 75,
            days_since,
            is_admin=is_webchat or self._is_admin_qq(qq),
        )
        return score, level, exchanges, active_days, int(impression), int(moral or 75)

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

        umo = str(event.unified_msg_origin or "")
        self._bump_activity(qq, umo, name)

        buffer = self._buffers.setdefault(qq, [])
        buffer.append(
            {
                "time": time.time(),
                "name": name,
                "umo": umo,
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
        self._profile_tasks.add(task)

        def _done(_t, q=qq):
            self._tasks.discard(q)
            self._profile_tasks.discard(_t)

        task.add_done_callback(_done)

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
            line = f"{e['name'] or qq}：{e['user']}\n我：{e['assistant']}"
            budget -= len(line)
            if budget < 0:
                break
            convo.append(line)
        recent = "\n\n".join(convo) or "（暂无可用对话）"

        old_score = parsed["moral_score"]
        if old_score is None:
            old_score = int(self._cfg("moral_initial", 75))
        today = time.strftime("%Y-%m-%d")
        prompt = build_profile_prompt(old_md, recent, today)
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
            system_prompt=PROFILE_SYSTEM_PROMPT,
        )
        body = clean_llm_markdown(getattr(result, "completion_text", ""))
        if not looks_like_profile(body):
            logger.warning(f"[{NAME}] 模型输出不像画像，丢弃（{qq}）")
            return

        # 印象分：模型给绝对值，代码做平滑，避免一次对话大起大落
        old_impression = parsed["impression_score"]
        if old_impression is None:
            old_impression = int(self._cfg("impression_initial", 50))
        raw_impression = extract_impression(body, old_impression)
        impression_score = smooth_score(
            old_impression,
            raw_impression,
            float(self._cfg("impression_smooth_alpha", 0.3)),
        )
        body = strip_impression(body)

        # 道德评价：模型只给本轮新增佐证条目，总分由代码累加（避免模型算错）
        base_body, new_entries = split_moral_section(body)
        if bool(self._cfg("moral_enabled", True)):
            old_entries = [
                line
                for line in moral_section(old_md).splitlines()
                if line.strip().startswith("- [")
            ]
            moral_score, entries = apply_moral_delta(
                old_entries, new_entries, old_score
            )
            if entries:
                body = base_body + "\n\n" + build_moral_section(moral_score, entries)
            else:
                body = base_body
        else:
            moral_score, body = old_score, base_body

        state = self._user_state(qq)
        exchanges = max(
            int(parsed["exchanges"] or 0) + len(snapshot),
            int(state.get("total_messages") or 0),
        )
        active_days = (
            len(state.get("active_days") or [])
            or int(parsed.get("active_days") or 0)
        )
        last_seen_ts = float(state.get("last_seen_ts") or 0)
        days_since = (time.time() - last_seen_ts) / 86400 if last_seen_ts else 0.0
        is_webchat = str(umo or "").startswith("webchat:")
        fam_score, fam_level = compute_familiarity(
            exchanges,
            active_days,
            impression_score,
            moral_score,
            days_since,
            is_admin=is_webchat or self._is_admin_qq(qq),
        )
        first_ts = float(state.get("first_ts") or time.time())
        first_seen = time.strftime("%Y-%m-%d", time.localtime(first_ts))
        last_seen = (
            time.strftime("%Y-%m-%d %H:%M", time.localtime(last_seen_ts))
            if last_seen_ts
            else ""
        )
        md = render_profile(
            qq,
            new_name,
            history,
            body,
            time.time(),
            exchanges,
            moral_score=moral_score,
            impression_score=impression_score,
            familiarity_score=fam_score,
            familiarity_level=fam_level,
            active_days=active_days,
            first_seen=first_seen,
            last_seen=last_seen,
        )
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(md)
        os.replace(tmp, path)
        logger.info(
            f"[{NAME}] 画像已更新：{new_name or qq}（{qq}），"
            f"本次素材 {len(snapshot)} 条，熟悉度 {fam_level}（{fam_score}），"
            f"印象 {impression_score}，道德 {moral_score}"
        )

    # ---------------- 聊天注入 ----------------
    def _level_of(self, qq: str, md: str) -> str:
        parsed = parse_profile(md)
        score = parsed["moral_score"]
        if score is None:
            # 兼容没有 frontmatter 评分的旧档案：读正文里的「当前评分」行
            score = extract_score(md, default=None)
        return moral_level(
            score,
            int(self._cfg("moral_warn_threshold", 70)),
            int(self._cfg("moral_bad_threshold", 40)),
        )

    def _cached_score(self, qq: str) -> int | None:
        """忽略门用的评分（300 秒缓存，避免每条群消息都读盘）。"""
        now = time.time()
        hit = self._score_cache.get(qq)
        if hit and now - hit[0] < 300:
            return hit[1]
        score = None
        try:
            with open(self._profile_path(qq), encoding="utf-8") as f:
                score = parse_profile(f.read())["moral_score"]
        except Exception:
            score = None
        if len(self._score_cache) > 200:
            self._score_cache.clear()
        self._score_cache[qq] = (now, score)
        return score

    @filter.event_message_type(filter.EventMessageType.ALL, priority=(1 << 31) - 3)
    async def ignore_gate(self, event: AstrMessageEvent):
        """恶劣/警戒用户的消息按概率直接忽略（等价于降低回复触发阈值）。

        - 群聊：@ 机器人和命令不拦（当面指责需要她能回话）；
        - 私聊：默认也降频（概率更低），但**所有者和管理员永不忽略**；
        - 命令一律放行。
        """
        if not self._enabled() or not bool(self._cfg("moral_enabled", True)):
            return
        text = str(event.message_str or "")
        if text.startswith(("/", "！")):
            return
        comps = getattr(event.message_obj, "message", None) or []
        self_id = str(event.get_self_id() or "")
        is_private = bool(getattr(event, "is_private_chat", lambda: False)())
        if not is_private and any(
            isinstance(c, At) and str(getattr(c, "qq", "")) == self_id for c in comps
        ):
            return
        qq = str(getattr(event, "get_sender_id", lambda: "")() or "")
        if not qq:
            return
        # 所有者 / 管理员永不忽略（哪怕评分再低，也要能跟他说话）
        if self._is_privileged(event, qq):
            return
        level = moral_level(
            self._cached_score(qq),
            int(self._cfg("moral_warn_threshold", 70)),
            int(self._cfg("moral_bad_threshold", 40)),
        )
        if level == "正常":
            return
        if is_private:
            if not bool(self._cfg("ignore_private_enabled", True)):
                return
            chance_warn = int(self._cfg("ignore_chance_private_warn", 20))
            chance_bad = int(self._cfg("ignore_chance_private_bad", 40))
            where = "私聊"
        else:
            chance_warn = int(self._cfg("ignore_chance_warn", 30))
            chance_bad = int(self._cfg("ignore_chance_bad", 60))
            where = "群"
        if should_ignore(level, chance_warn, chance_bad, random.random()):
            event.stop_event()
            logger.info(f"[{NAME}] 已忽略 {level} 用户 {qq} 的{where}消息（回复阈值降低）")

    def _is_privileged(self, event: AstrMessageEvent, qq: str) -> bool:
        """所有者 / 管理员 / 网页测试台：不受道德评分降频影响。"""
        # 网页测试台是所有者自己调试用的，一律豁免（其用户名不是 QQ 号，无法与 admins_id 匹配）
        if str(event.get_platform_name() or "") == "webchat":
            return True
        owner = str(self._cfg("owner_session", "") or "").strip()
        if owner and str(event.unified_msg_origin or "") == owner:
            return True
        try:
            admins = self.context.get_config().get("admins_id") or []
            if str(qq) in {str(a) for a in admins}:
                return True
        except Exception:
            pass
        try:
            if callable(getattr(event, "is_admin", None)) and event.is_admin():
                return True
        except Exception:
            pass
        return False

    async def _attitude_delay(self, level: str) -> None:
        base = (
            int(self._cfg("delay_bad_seconds", 35))
            if level == "恶劣"
            else int(self._cfg("delay_warn_seconds", 12))
        )
        if base <= 0:
            return
        delay = random.uniform(max(1.0, base * 0.6), base * 1.4)
        logger.info(f"[{NAME}] 对 {level} 用户的回复延迟 {delay:.0f}s")
        await asyncio.sleep(delay)

    # ---------------- 按熟悉度主动消息 ----------------
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

    def _in_active_window(self, now_ts: float | None = None) -> bool:
        hhmm = time.strftime("%H:%M", time.localtime(now_ts or time.time()))
        return in_time_windows(
            str(self._cfg("proactive_windows", "12:00-13:30,18:00-22:00")),
            hhmm,
        )

    def _delay_until_window(self) -> float:
        if self._in_active_window():
            return 0.0
        spec = str(self._cfg("proactive_windows", "12:00-13:30,18:00-22:00"))
        now = time.time()
        for offset in range(1, 1441):
            if in_time_windows(
                spec, time.strftime("%H:%M", time.localtime(now + offset * 60))
            ):
                return float(offset * 60)
        return 3600.0

    def _vlife_activity(self) -> dict | None:
        """读虚拟人生今日日程，返回当前时段的活动；未安装/无日程返回 None。"""
        if not bool(self._cfg("virtual_life_adapt", True)):
            return None
        try:
            if not self.context.get_registered_star("astrbot_plugin_virtual_life"):
                return None
            path = (
                Path(str(StarTools.get_data_dir("astrbot_plugin_virtual_life")))
                / "plans.json"
            )
            data = json.loads(path.read_text(encoding="utf-8"))
            plan = pick_today_plan(
                data, time.strftime("%Y-%m-%d"), self._persona_name()
            )
            if not plan:
                return None
            item = current_timeline_item(plan, time.strftime("%H:%M"))
            if item:
                logger.info(
                    f"[{NAME}] 虚拟日程当前活动：{activity_line(item)}"
                    f"（{item.get('state')}/{item.get('availability')}）"
                )
            return item
        except FileNotFoundError:
            return None
        except Exception as exc:
            logger.debug(f"[{NAME}] 虚拟日程读取失败：{exc}")
            return None

    async def _proactive_loop(self) -> None:
        minutes = max(5, int(self._cfg("proactive_check_minutes", 15)))
        windows = str(self._cfg("proactive_windows", "12:00-13:30,18:00-22:00"))
        logger.info(
            f"[{NAME}] 按熟悉度主动消息循环已启动"
            f"（时间窗 {windows}，窗内每 {minutes} 分钟检查）"
        )
        await asyncio.sleep(30)
        while True:
            try:
                delay = self._delay_until_window()
                if delay > 0:
                    logger.info(f"[{NAME}] 距下个主动时间窗 {delay / 60:.0f} 分钟")
                    await asyncio.sleep(delay)
                await self._proactive_tick()
            except Exception as exc:
                logger.warning(f"[{NAME}] 主动消息检查失败：{exc}")
            await asyncio.sleep(minutes * 60)

    async def _proactive_tick(self) -> None:
        if not self._enabled() or not bool(self._cfg("proactive_enabled", False)):
            return
        now = time.time()
        if not self._in_active_window(now):
            return
        if in_quiet_hours(
            str(self._cfg("proactive_quiet_hours", "23-7")),
            time.localtime(now).tm_hour,
        ):
            return
        activity = self._vlife_activity()
        if not activity_allows_proactive(activity):
            logger.info(
                f"[{NAME}] 当前虚拟日程不适合主动聊天：{activity_line(activity)}"
            )
            return
        users = self._load_state().get("users", {})
        if not isinstance(users, dict):
            return
        max_send = max(1, int(self._cfg("proactive_max_per_check", 1)))
        sent = 0
        for qq, state in list(users.items()):
            if sent >= max_send:
                break
            if not str(qq).isdigit() or not isinstance(state, dict):
                continue
            if bool(self._cfg("proactive_exclude_admins", True)) and self._is_admin_qq(qq):
                continue
            umo = str(state.get("last_private_umo") or "")
            if ":FriendMessage:" not in umo or umo.startswith("webchat:"):
                continue
            last_seen = float(state.get("last_seen_ts") or 0)
            if not last_seen:
                continue
            if now - last_seen > float(self._cfg("proactive_active_days", 14)) * 86400:
                continue
            if now - last_seen < float(self._cfg("proactive_min_idle_minutes", 120)) * 60:
                continue
            last_pro = float(state.get("last_proactive_ts") or 0)
            if last_pro and last_seen <= last_pro:
                # 上次主动后对方一直没回，别连着打扰
                continue
            if last_pro and now - last_pro < float(
                self._cfg("proactive_cooldown_hours", 36)
            ) * 3600:
                continue
            today = time.strftime("%Y-%m-%d", time.localtime(now))
            if state.get("proactive_date") == today and int(
                state.get("proactive_count") or 0
            ) >= int(self._cfg("proactive_daily_max", 1)):
                continue
            try:
                with open(self._profile_path(qq), encoding="utf-8") as f:
                    md = f.read()
            except Exception:
                continue
            fam_score, fam_level, *_ = self._familiarity_of(qq, md)
            if fam_score < int(self._cfg("proactive_min_familiarity", 44)):
                continue
            if random.random() > float(self._cfg("proactive_chance", 0.15)):
                continue
            text = await self._generate_proactive(
                qq, umo, md, fam_level, fam_score, activity
            )
            if not text:
                continue
            if not await self._send_proactive(umo, text):
                continue
            state["last_proactive_ts"] = now
            if state.get("proactive_date") == today:
                state["proactive_count"] = int(state.get("proactive_count") or 0) + 1
            else:
                state["proactive_date"] = today
                state["proactive_count"] = 1
            self._save_state()
            sent += 1
            logger.info(
                f"[{NAME}] 按熟悉度主动找 {state.get('last_name') or qq}："
                f"{fam_level}（{fam_score}）→ {text[:60]}"
            )

    async def _generate_proactive(
        self,
        qq: str,
        umo: str,
        md: str,
        fam_level: str,
        fam_score: int,
        activity: dict | None = None,
    ) -> str:
        provider = None
        try:
            provider = await self.context.get_using_provider_async(umo=umo)
            if provider is None:
                provider = await self.context.get_using_provider_async()
        except Exception:
            provider = None
        if provider is None:
            return ""
        parsed = parse_profile(md)
        name = parsed.get("name") or qq
        summary = profile_summary(md, 350)
        recent = self._buffers.get(qq, [])[-3:]
        recent_text = "\n".join(
            f"{e.get('name') or qq}：{e.get('user')}\n我：{e.get('assistant')}"
            for e in recent
        )
        now_text = time.strftime("%Y-%m-%d %H:%M", time.localtime())
        act = activity_line(activity)
        prompt = (
            f"你想主动找 {name} 说句话，不是回复，是你先开口。\n"
            f"你们的关系：{fam_level}（熟悉度 {fam_score}/100）。\n"
            f"你私下记的关于 TA 的印象：{summary}\n"
            + (f"最近你们聊过：\n{recent_text}\n" if recent_text else "")
            + f"现在是 {now_text}。\n"
            + (
                f"你现在正在：{act}。可以自然结合正在做的事说一句——"
                "分享此刻看到/吃到/碰到的小事，或者问 TA 在干嘛。\n"
                if act
                else ""
            )
            + "要求：用第一人称、口语，像平时 QQ 聊天一样，一句自然的开场；"
            "不超过 40 字；可以延续最近的话题、关心近况，或者分享一件你今天的小事；"
            "不要提印象、熟悉度、分数、系统、画像、日程这些词，不要客服腔。只输出这一句。"
        )
        persona_prompt = ""
        try:
            persona = await self.context.persona_manager.get_persona(
                str(self._cfg("proactive_persona_id", "小雪"))
            )
            persona_prompt = str(getattr(persona, "system_prompt", "") or "")
        except Exception:
            persona_prompt = (
                "你是一个大学生妹妹，叫小雪，用第一人称、口语，像平时 QQ 聊天一样说话。"
            )
        kwargs = {"prompt": prompt}
        if persona_prompt:
            kwargs["system_prompt"] = persona_prompt
        try:
            result = await asyncio.wait_for(
                provider.text_chat(**kwargs), timeout=60
            )
        except Exception as exc:
            logger.info(f"[{NAME}] 生成主动消息失败：{exc}")
            return ""
        text = str(getattr(result, "completion_text", "") or "").strip()
        return text[:160]

    async def _send_proactive(self, umo: str, text: str) -> bool:
        try:
            sent = await self.context.send_message(
                umo, MessageChain(chain=[Plain(text)])
            )
        except Exception as exc:
            logger.warning(f"[{NAME}] 主动消息发送失败：{exc}")
            return False
        if sent:
            await self._remember_assistant(umo, text)
        return bool(sent)

    async def _remember_assistant(self, umo: str, text: str) -> None:
        """主动消息不走正常回复链，手动补进对话历史，下一轮她才知道自己说过。"""
        manager = getattr(self.context, "conversation_manager", None)
        if manager is None or not umo or not text:
            return
        lock = self._history_locks.setdefault(umo, asyncio.Lock())
        async with lock:
            try:
                cid = await manager.get_curr_conversation_id(umo)
                if not cid:
                    return
                conv = await manager.get_conversation(umo, cid)
                if conv is None:
                    return
                history = (
                    json.loads(conv.history)
                    if isinstance(conv.history, str)
                    else conv.history
                )
                if not isinstance(history, list):
                    return
                if history:
                    last = history[-1]
                    if isinstance(last, dict) and last.get("role") == "assistant":
                        if last.get("tool_calls"):
                            return
                        content = last.get("content")
                        if isinstance(content, str) and text in content:
                            return
                        if isinstance(content, list):
                            joined = "".join(
                                str(part.get("text") or "")
                                for part in content
                                if isinstance(part, dict)
                            )
                            if text in joined:
                                return
                history.append(
                    {"role": "assistant", "content": [{"type": "text", "text": text}]}
                )
                await manager.update_conversation(
                    umo, conversation_id=cid, history=history
                )
            except Exception as exc:
                logger.info(f"[{NAME}] 主动消息写入历史失败：{exc}")

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
        level = (
            self._level_of(qq, md)
            if bool(self._cfg("moral_enabled", True))
            else "正常"
        )
        if level != "正常":
            await self._attitude_delay(level)
        fam_score, fam_level, exchanges, active_days, impression, moral = (
            self._familiarity_of(
                qq,
                md,
                is_webchat=str(event.get_platform_name() or "") == "webchat",
            )
        )
        summary = profile_summary(md, int(self._cfg("inject_limit_chars", 400)))
        familiarity = (
            f"\n\n[熟悉度] {fam_level}（{fam_score}/100；聊过 {exchanges} 次、"
            f"活跃 {active_days} 天；印象 {impression}、道德 {moral}）："
            f"{familiarity_guidance(fam_level)}"
        )
        req.system_prompt = prompt + "\n\n" + summary + familiarity
        if level != "正常":
            block = moral_injection(md, level, int(self._cfg("inject_limit_chars", 400)))
            req.system_prompt += "\n\n" + block

    async def terminate(self) -> None:
        """插件被禁用/重载时停掉后台任务并落盘状态。"""
        task = self._proactive_task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        self._proactive_task = None
        running = [t for t in self._profile_tasks if not t.done()]
        for t in running:
            t.cancel()
        if running:
            await asyncio.gather(*running, return_exceptions=True)
        self._profile_tasks.clear()
        self._tasks.clear()
        self._save_state()
