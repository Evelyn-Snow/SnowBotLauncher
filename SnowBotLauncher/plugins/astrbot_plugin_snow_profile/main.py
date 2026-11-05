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
import copy
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
    RELATION_MARK,
    RELATION_SYSTEM_PROMPT,
    SUMMARY_MARK,
    apply_moral_delta,
    build_gossip_prompt,
    build_moral_section,
    build_profile_prompt,
    build_relation_prompt,
    clean_llm_markdown,
    clean_relation_item,
    clean_suspicion_item,
    compute_familiarity,
    current_timeline_item,
    activity_allows_proactive,
    activity_line,
    effective_confidence,
    evidence_speakers,
    extract_impression,
    extract_score,
    familiarity_guidance,
    find_relation_edge,
    gossip_candidates,
    gossip_fallback_question,
    has_relation_cue,
    in_quiet_hours,
    in_time_windows,
    looks_like_profile,
    merge_name_history,
    merge_relation_items,
    merge_relation_suspects,
    migrate_relations,
    moral_injection,
    moral_level,
    moral_section,
    parse_profile,
    parse_relation_bundle,
    pick_today_plan,
    profile_summary,
    relation_injection,
    render_profile,
    should_ignore,
    should_update,
    smooth_score,
    split_moral_section,
    strip_impression,
)
from .privacy import (
    build_id_map,
    collect_ids,
    redact_ids,
    sanitize_context_text,
)
from .shared_memory import (
    SHARED_MARK,
    build_card_prompt,
    clean_card,
    format_shared_block,
    load_relation_index,
    merge_cards,
    parse_cards_payload,
    select_cards,
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
        self._gossip_task: asyncio.Task | None = None
        # 关系网：群消息短缓冲 + 单群一次分析任务；结果写 relations.json
        self._rel_buffers: dict[str, list[dict]] = {}
        self._rel_new: dict[str, int] = {}
        self._rel_tasks: set[str] = set()
        self._rel_data: dict | None = None
        self._rel_lock = threading.RLock()
        self._rel_last_attempt: dict[str, float] = {}
        # 跨会话共享记忆：按会话缓冲、汇总成带分享评级的卡片
        self._shared_buffers: dict[str, list[dict]] = {}
        self._shared_new: dict[str, int] = {}
        self._shared_tasks: set[str] = set()
        self._shared_data: dict | None = None
        self._shared_lock = threading.RLock()
        self._shared_rel_cache: tuple[float, dict] = (0.0, {})

    async def initialize(self) -> None:
        if bool(self.conf.get("proactive_enabled", False)):
            self._proactive_task = asyncio.create_task(self._proactive_loop())
        if bool(self.conf.get("relation_enabled", True)) and bool(
            self.conf.get("gossip_enabled", True)
        ):
            self._gossip_task = asyncio.create_task(self._gossip_loop())

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

    # ---------------- 关系网存储 ----------------
    def _relations_path(self) -> str:
        raw = str(self._cfg("relations_dir", "") or "").strip()
        if raw:
            folder = os.path.expandvars(raw)
        else:
            parent = os.path.dirname(os.path.abspath(self._profiles_dir()))
            folder = os.path.join(parent, "关系")
        os.makedirs(folder, exist_ok=True)
        return os.path.join(folder, "relations.json")

    def _relations(self) -> dict:
        with self._rel_lock:
            if self._rel_data is not None:
                return self._rel_data
            data: dict = {}
            try:
                with open(self._relations_path(), encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    data = loaded
            except Exception:
                data = {}
            data = migrate_relations(data)
            data.setdefault("edges", [])
            data.setdefault("scopes", {})
            self._rel_data = data
            return data

    def _save_relations(self) -> None:
        path = self._relations_path()
        with self._rel_lock:
            data = self._relations()
            data["updated_at"] = time.time()
            tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(tmp, path)
            except Exception as exc:
                logger.warning(f"[{NAME}] 关系网保存失败：{exc}")

    def _scope_relations(self, umo: str, kind: str = "") -> dict:
        data = self._relations()
        scope = data["scopes"].setdefault(umo, {})
        scope.setdefault(
            "kind",
            kind or ("group" if ":GroupMessage:" in umo else "private"),
        )
        scope.setdefault("name", "")
        scope.setdefault("last_analyzed_ts", 0)
        scope.setdefault("runs", {})
        return scope

    # ---------------- 共享记忆存储 ----------------
    def _shared_dir(self) -> str:
        raw = str(self._cfg("shared_memory_dir", "") or "").strip()
        if raw:
            folder = os.path.expandvars(raw)
        else:
            parent = os.path.dirname(os.path.abspath(self._profiles_dir()))
            folder = os.path.join(parent, "共享记忆")
        os.makedirs(folder, exist_ok=True)
        return folder

    def _shared_path(self) -> str:
        return os.path.join(self._shared_dir(), "cards.json")

    def _shared(self) -> dict:
        with self._shared_lock:
            if self._shared_data is not None:
                return self._shared_data
            data: dict = {}
            try:
                with open(self._shared_path(), encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    data = loaded
            except Exception:
                data = {}
            if not isinstance(data.get("cards"), list):
                data["cards"] = []
            if not isinstance(data.get("scopes"), dict):
                data["scopes"] = {}
            data.setdefault("version", 1)
            self._shared_data = data
            return data

    def _save_shared(self) -> None:
        path = self._shared_path()
        with self._shared_lock:
            data = self._shared()
            data["updated_at"] = time.time()
            tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(tmp, path)
            except Exception as exc:
                logger.warning(f"[{NAME}] 共享记忆保存失败：{exc}")

    def _shared_relation_index(self) -> dict:
        path = self._relations_path()
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return {}
        cached_mtime, cached = self._shared_rel_cache
        if mtime == cached_mtime:
            return cached
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            index = load_relation_index(data)
        except Exception:
            index = {}
        self._shared_rel_cache = (mtime, index)
        return index

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
        group_getter = getattr(event, "get_group_id", None)
        group_id = ""
        if callable(group_getter):
            try:
                group_id = str(group_getter() or "")
            except Exception:
                group_id = ""
        is_group = bool(group_id) or "GroupMessage" in str(
            event.unified_msg_origin or ""
        )
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

        if bool(self._cfg("shared_memory_enabled", True)) and platform != "webchat":
            scope = {
                "scope": umo,
                "kind": "group" if is_group else "private",
                "label": self._shared_scope_label(event, is_group, name, qq),
                "public_label": "一个群聊" if is_group else "一个私聊",
            }
            rows = self._shared_buffers.setdefault(umo, [])
            rows.append(
                {
                    "time": time.time(),
                    "scope": umo,
                    "kind": scope["kind"],
                    "label": scope["label"],
                    "public_label": scope["public_label"],
                    "sender": qq,
                    "name": name,
                    "user": user_text[:500],
                    "assistant": reply_text[:800],
                }
            )
            cap = max(8, int(self._cfg("shared_buffer_size", 40)))
            self._shared_buffers[umo] = rows[-cap:]
            self._shared_new[umo] = self._shared_new.get(umo, 0) + 1
            if self._shared_due(umo):
                self._schedule_shared(umo)

        await self._maybe_schedule(qq)

    def _shared_scope_label(
        self, event: AstrMessageEvent, is_group: bool, name: str, qq: str
    ) -> str:
        if is_group:
            try:
                group_name = str(
                    getattr(event.message_obj.group, "group_name", "") or ""
                ).strip()
            except Exception:
                group_name = ""
            return f"群聊「{group_name}」" if group_name else "一个群聊"
        return f"和{name or qq}的私聊"

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

    # ---------------- 共享记忆卡片 ----------------
    def _shared_due(self, umo: str) -> bool:
        if not bool(self._cfg("shared_memory_enabled", True)):
            return False
        rows = self._shared_buffers.get(umo) or []
        min_exchanges = max(2, int(self._cfg("shared_min_exchanges", 10)))
        if len(rows) < min_exchanges:
            return False
        if self._shared_new.get(umo, 0) < min_exchanges:
            return False
        now = time.time()
        if in_quiet_hours(
            str(self._cfg("shared_quiet_hours", "0-7")),
            time.localtime(now).tm_hour,
        ):
            return False
        scope = self._shared()["scopes"].setdefault(umo, {})
        today = time.strftime("%Y-%m-%d", time.localtime(now))
        if scope.get("date") != today:
            scope["date"] = today
            scope["count"] = 0
        if int(scope.get("count") or 0) >= max(
            1, int(self._cfg("shared_max_calls_per_day", 12))
        ):
            return False
        interval = max(
            10, int(self._cfg("shared_min_interval_minutes", 60))
        ) * 60
        return now - float(scope.get("last_ts") or 0) >= interval

    def _schedule_shared(self, umo: str) -> None:
        if umo in self._shared_tasks:
            return
        self._shared_tasks.add(umo)
        task = asyncio.create_task(self._update_shared(umo))
        self._profile_tasks.add(task)

        def _done(t, key=umo):
            self._shared_tasks.discard(key)
            self._profile_tasks.discard(t)

        task.add_done_callback(_done)

    async def _update_shared(self, umo: str) -> None:
        snapshot = list(self._shared_buffers.get(umo, []))
        if not snapshot:
            return
        now = time.time()
        scope = self._shared()["scopes"].setdefault(umo, {})
        scope["last_ts"] = now
        scope["count"] = int(scope.get("count") or 0) + 1
        self._shared_new[umo] = 0
        try:
            try:
                provider = await self.context.get_using_provider_async(umo=umo)
            except Exception:
                provider = None
            if provider is None:
                return
            source = {
                "scope": umo,
                "kind": str(snapshot[-1].get("kind") or ""),
                "label": str(snapshot[-1].get("label") or "一个对话"),
                "public_label": str(
                    snapshot[-1].get("public_label") or "一个对话"
                ),
            }
            prompt = build_card_prompt(source["label"], snapshot)
            result = await asyncio.wait_for(
                provider.text_chat(
                    prompt=prompt,
                    system_prompt=(
                        "你是这个聊天机器人，正在整理只给自己看的共享记忆卡片。"
                        "只写真实发生的事，不编造，不写 QQ 号或群号。"
                    ),
                ),
                timeout=90,
            )
            raw_cards = parse_cards_payload(
                getattr(result, "completion_text", "") or ""
            )
            participants = {
                str(row.get("sender") or "") for row in snapshot if row.get("sender")
            }
            cleaned = [
                card
                for card in (
                    clean_card(item, participants) for item in raw_cards[:6]
                )
                if card is not None
            ]
            ids = self._known_ids() | participants
            for card in cleaned:
                card["summary"] = redact_ids(card["summary"], ids)
                card["topics"] = [
                    redact_ids(topic, ids) for topic in card.get("topics") or []
                ]
                card["reason"] = redact_ids(card.get("reason", ""), ids)
            with self._shared_lock:
                changed = merge_cards(
                    self._shared()["cards"],
                    cleaned,
                    source,
                    now,
                    cap=max(50, int(self._cfg("shared_max_cards", 500))),
                )
            if changed:
                logger.info(
                    f"[{NAME}] 共享记忆更新：{source['label']}，"
                    f"新增/合并 {changed} 张卡片"
                )
        except asyncio.TimeoutError:
            logger.warning(f"[{NAME}] 共享记忆汇总超时（{umo}）")
        except Exception as exc:
            logger.warning(f"[{NAME}] 共享记忆汇总失败（{umo}）：{exc}")
        finally:
            self._save_shared()

    def _shared_audience(self, event: AstrMessageEvent, qq: str) -> dict:
        umo = str(event.unified_msg_origin or "")
        group_getter = getattr(event, "get_group_id", None)
        group_id = ""
        if callable(group_getter):
            try:
                group_id = str(group_getter() or "")
            except Exception:
                group_id = ""
        is_group = bool(group_id) or "GroupMessage" in umo
        members: set[str] = {qq}
        if is_group:
            try:
                for member in event.message_obj.group.members or []:
                    member_id = str(getattr(member, "user_id", "") or "")
                    if member_id:
                        members.add(member_id)
            except Exception:
                pass
            if len(members) <= 1:
                for row in self._rel_buffers.get(umo, [])[-80:]:
                    sender = str(row.get("sender") or "")
                    if sender:
                        members.add(sender)
        return {
            "sender": qq,
            "scope": umo,
            "is_group": is_group,
            "is_owner": self._is_admin_qq(qq),
            "group_members": members,
        }

    def _shared_injection(
        self, event: AstrMessageEvent, qq: str, req
    ) -> str:
        if not bool(self._cfg("shared_memory_enabled", True)):
            return ""
        if str(event.get_platform_name() or "") == "webchat":
            return ""
        audience = self._shared_audience(event, qq)
        cards = select_cards(
            self._shared().get("cards") or [],
            str(getattr(event, "message_str", "") or ""),
            audience,
            self._shared_relation_index(),
            time.time(),
            top_k=max(1, int(self._cfg("shared_inject_top_k", 4))),
            min_score=float(self._cfg("shared_min_relevance", 0.15)),
            min_confidence=float(
                self._cfg("shared_relation_min_confidence", 0.6)
            ),
        )
        return format_shared_block(
            cards,
            audience,
            max(120, int(self._cfg("shared_inject_limit_chars", 600))),
        )

    # ---------------- 关系网采集与推断 ----------------
    @filter.event_message_type(
        filter.EventMessageType.ALL, priority=(1 << 31) + 20
    )
    async def observe_relations(self, event: AstrMessageEvent):
        """在高优先级记录群聊/私聊原文，供关系推断用；不拦截、不修改消息。"""
        if not self._enabled() or not bool(self._cfg("relation_enabled", True)):
            return
        if event.get_extra("_snow_burst_merged"):
            return
        umo = str(event.unified_msg_origin or "")
        is_group = ":GroupMessage:" in umo
        if (
            not umo
            or umo.startswith("webchat:")
            or not (is_group or ":FriendMessage:" in umo)
        ):
            return
        text = str(event.message_str or "").strip()
        if not text or text.startswith(("/", "！", "!")):
            return
        sender = str(event.get_sender_id() or "")
        if not sender or sender == str(event.get_self_id() or ""):
            return
        rows = self._rel_buffers.setdefault(umo, [])
        mid = str(getattr(event.message_obj, "message_id", "") or "")
        if mid and rows and str(rows[-1].get("id") or "") == mid:
            return
        name = ""
        try:
            name = str(event.get_sender_name() or "").strip()
        except Exception:
            pass
        rows.append(
            {
                "id": mid,
                "sender": sender,
                "name": name,
                "text": text[:300],
                "ts": time.time(),
            }
        )
        cap = max(40, int(self._cfg("relation_buffer_size", 200)))
        if len(rows) > cap:
            del rows[:-cap]
        scope = self._scope_relations(umo, "group" if is_group else "private")
        members = scope.setdefault("members", {})
        if name or sender not in members:
            members[sender] = name
        if len(members) > 50:
            for qq in list(members)[:-50]:
                members.pop(qq, None)
        if is_group:
            try:
                group_name = str(
                    getattr(event.message_obj.group, "group_name", "") or ""
                )
                if group_name:
                    scope["name"] = group_name
            except Exception:
                pass
        self._rel_new[umo] = self._rel_new.get(umo, 0) + 1
        if self._relation_ready(umo):
            self._schedule_relations(umo)

    def _relation_ready(self, umo: str) -> bool:
        rows = self._rel_buffers.get(umo) or []
        is_group = ":GroupMessage:" in umo
        senders = {r.get("sender") for r in rows[-80:]}
        if is_group and len(senders) < 2:
            return False
        if not is_group and not senders:
            return False
        if self._rel_new.get(umo, 0) < (2 if is_group else 1):
            return False
        now = time.time()
        if in_quiet_hours(
            str(self._cfg("quiet_hours", "0-6")),
            time.localtime(now).tm_hour,
        ):
            return False
        scope = self._scope_relations(umo)
        today = time.strftime("%Y-%m-%d", time.localtime(now))
        runs = scope.get("runs") or {}
        if int(runs.get(today) or 0) >= max(
            1, int(self._cfg("relation_max_per_day", 6))
        ):
            return False
        last = max(
            float(scope.get("last_analyzed_ts") or 0),
            float(self._rel_last_attempt.get(umo) or 0),
        )
        recent_text = "\n".join(
            str(row.get("text") or "") for row in rows[-3:]
        )
        cue = bool(
            self._cfg("relation_keyword_trigger", True)
        ) and has_relation_cue(recent_text)
        # 私聊只有一个人，必须出现明确的关系词才值得分析；否则没有可配对的双方
        if not is_group and not cue:
            return False
        if cue:
            # 私聊只有一个人，一句明确点名就值得看；群聊仍要求几条上下文
            need = (
                1
                if not is_group
                else max(2, int(self._cfg("relation_keyword_min_messages", 6)))
            )
            interval = 30 * 60
        else:
            need = max(6, int(self._cfg("relation_min_messages", 40)))
            interval = max(
                600, int(self._cfg("relation_min_interval_minutes", 180)) * 60
            )
        if self._rel_new.get(umo, 0) < need:
            return False
        return now - last >= interval

    def _schedule_relations(self, umo: str) -> None:
        if umo in self._rel_tasks:
            return
        self._rel_tasks.add(umo)
        task = asyncio.create_task(self._update_relations(umo))
        self._profile_tasks.add(task)

        def _done(t, key=umo):
            self._rel_tasks.discard(key)
            self._profile_tasks.discard(t)

        task.add_done_callback(_done)

    def _profile_names(self) -> dict[str, list[str]]:
        """已知用户的昵称 → QQ，用于把跨群/私聊里提到的名字映射到人。"""
        found: dict[str, list[str]] = {}

        def add(name: str, qq: str) -> None:
            name = str(name or "").strip()
            qq = str(qq or "").strip()
            if len(name) >= 2 and qq.isdigit():
                found.setdefault(name, []).append(qq)

        try:
            for path in Path(self._profiles_dir()).glob("*.md"):
                try:
                    parsed = parse_profile(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                add(parsed["name"], parsed["qq"] or path.stem)
        except Exception:
            pass
        for edge in self._relations().get("edges") or []:
            for qq, name in (edge.get("names") or {}).items():
                add(name, qq)
        return found

    def _relation_members(
        self, rows: list[dict]
    ) -> tuple[list[tuple[str, str]], dict]:
        names: dict[str, str] = {}
        for row in rows:
            sender = str(row.get("sender") or "")
            if not sender:
                continue
            name = str(row.get("name") or "").strip()
            if name or sender not in names:
                names[sender] = name
        transcript = "\n".join(
            f"{row.get('name') or ''} {row.get('text') or ''}" for row in rows
        )
        for name, qqs in self._profile_names().items():
            unique = sorted(set(qqs))
            if len(unique) != 1 or name not in transcript:
                continue
            qq = unique[0]
            names.setdefault(qq, name)
            if len(names) >= 40:
                break
        return list(names.items()), names

    def _existing_relation_lines(
        self,
        edges: list[dict],
        member_ids: set[str],
        now: float,
        half_life_days: float,
    ) -> list[str]:
        lines = []
        for edge in edges or []:
            a, b = str(edge.get("a") or ""), str(edge.get("b") or "")
            if a not in member_ids or b not in member_ids:
                continue
            types = []
            for rtype, entry in (edge.get("types") or {}).items():
                conf = effective_confidence(entry, now, half_life_days)
                if conf >= 0.5:
                    types.append(f"{rtype}({conf:.1f})")
            if not types:
                continue
            names = edge.get("names") or {}
            lines.append(
                f"- {names.get(a) or '一个人'} 和 {names.get(b) or '一个人'}："
                + "、".join(types)
            )
        return lines[:20]

    async def _update_relations(self, umo: str) -> None:
        """对最近一段对话做一次保守的关系抽取；失败不影响聊天。"""
        snapshot = list(self._rel_buffers.get(umo, []))
        if not snapshot:
            return
        now = time.time()
        half_life = float(self._cfg("relation_half_life_days", 180))
        scope = self._scope_relations(umo)
        today = time.strftime("%Y-%m-%d", time.localtime(now))
        scope["last_analyzed_ts"] = now
        runs = scope.setdefault("runs", {})
        runs[today] = int(runs.get(today) or 0) + 1
        for old_day in sorted(runs)[:-14]:
            runs.pop(old_day, None)
        self._rel_new[umo] = 0
        self._rel_last_attempt[umo] = now
        changed = 0
        try:
            members, names = self._relation_members(snapshot)
            if len(members) < 2:
                return
            try:
                provider = await self.context.get_using_provider_async(umo=umo)
            except Exception:
                provider = None
            if provider is None:
                logger.info(f"[{NAME}] 关系网：没有可用模型，跳过本轮")
                return
            prompt = build_relation_prompt(
                str(scope.get("name") or umo.rsplit(":", 1)[-1]),
                members,
                snapshot,
                self._existing_relation_lines(
                    self._relations().get("edges") or [],
                    {qq for qq, _ in members},
                    now,
                    half_life,
                ),
            )
            result = await asyncio.wait_for(
                provider.text_chat(
                    prompt=prompt, system_prompt=RELATION_SYSTEM_PROMPT
                ),
                timeout=90,
            )
            payload = getattr(result, "completion_text", "") or ""
            items, suspicions = parse_relation_bundle(payload)
            items, suspicions = items[:20], suspicions[:20]
            transcript = "\n".join(
                f"{row.get('sender')} {row.get('name') or ''}：{row.get('text')}"
                for row in snapshot
            )
            member_ids = {qq for qq, _ in members}
            min_conf = float(self._cfg("relation_min_confidence", 0.75))
            current_senders = {
                str(row.get("sender") or "") for row in snapshot
            }
            cleaned = []
            for raw in items:
                item = clean_relation_item(
                    raw, member_ids, transcript, min_conf
                )
                if item is None:
                    continue
                speakers = evidence_speakers(item["evidence"], snapshot)
                if not (speakers & {item["a"], item["b"]}):
                    continue
                # 不在本会话里的人，必须在这句原话里被点名，否则可能张冠李戴
                for qq in {item["a"], item["b"]} - current_senders:
                    name = str(names.get(qq) or "")
                    if qq not in item["evidence"] and (
                        not name or name not in item["evidence"]
                    ):
                        break
                else:
                    cleaned.append(item)
            suspect_min = float(
                self._cfg("gossip_min_suspect_confidence", 0.5)
            )
            is_group = ":GroupMessage:" in umo
            cleaned_suspects = []
            for raw in suspicions:
                item = clean_suspicion_item(
                    raw, member_ids, current_senders, names, suspect_min
                )
                if item is None:
                    continue
                # 群里只猜测最近都露过面的人；私聊才允许点名已知的第三方
                if is_group and not {item["a"], item["b"]} <= current_senders:
                    continue
                cleaned_suspects.append(item)
            with self._rel_lock:
                relations = self._relations()
                changed = merge_relation_items(
                    relations["edges"],
                    cleaned,
                    names,
                    now,
                    scope=umo,
                )
                suspect_changed = merge_relation_suspects(
                    relations["edges"],
                    cleaned_suspects,
                    names,
                    now,
                    scope=umo,
                )
            if cleaned or cleaned_suspects:
                logger.info(
                    f"[{NAME}] 关系网更新：{umo}，确认 {changed} 条、"
                    f"猜测 {suspect_changed} 条（模型给出 {len(items)}/"
                    f"{len(suspicions)}，通过校验 {len(cleaned)}/"
                    f"{len(cleaned_suspects)}）"
                )
            else:
                logger.info(f"[{NAME}] 关系网：本轮没有可靠的新关系（{umo}）")
        except asyncio.TimeoutError:
            logger.warning(f"[{NAME}] 关系网推断超时（{umo}）")
        except Exception as exc:
            logger.warning(f"[{NAME}] 关系网推断失败（{umo}）：{exc}")
        finally:
            self._save_relations()

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
        ids = self._known_ids() | {qq}
        prompt = build_profile_prompt(
            redact_ids(old_md, ids), redact_ids(recent, ids), today
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

    # ---------------- 向熟人打听关系 ----------------
    def _gossip_window_ok(self, now: float) -> bool:
        if in_quiet_hours(
            str(self._cfg("gossip_quiet_hours", "23-7")),
            time.localtime(now).tm_hour,
        ):
            return False
        windows = str(
            self._cfg("gossip_windows", "12:00-13:30,18:00-22:00")
        ).strip()
        if not windows:
            return True
        return in_time_windows(
            windows, time.strftime("%H:%M", time.localtime(now))
        )

    def _gossip_budget_ok(self, now: float) -> bool:
        gossip = self._load_state().setdefault("gossip", {})
        today = time.strftime("%Y-%m-%d", time.localtime(now))
        if gossip.get("date") != today:
            gossip["date"] = today
            gossip["count"] = 0
        if int(gossip.get("count") or 0) >= max(
            0, int(self._cfg("gossip_max_per_day", 1))
        ):
            return False
        last = float(gossip.get("last_ts") or 0)
        if last and now - last < max(
            0.0, float(self._cfg("gossip_cooldown_hours", 20))
        ) * 3600:
            return False
        return True

    async def _gossip_loop(self) -> None:
        minutes = max(10, int(self._cfg("gossip_check_minutes", 60)))
        logger.info(
            f"[{NAME}] 关系打听循环已启动（每 {minutes} 分钟检查一次，"
            "只在有猜测且对方足够熟时开口）"
        )
        await asyncio.sleep(60)
        while True:
            try:
                if self._gossip_window_ok(time.time()):
                    await self._gossip_tick()
            except Exception as exc:
                logger.warning(f"[{NAME}] 关系打听失败：{exc}")
            await asyncio.sleep(minutes * 60)

    def _gossip_target(self, cand: dict) -> dict | None:
        scope = str(cand.get("scope") or "")
        meta = (self._relations().get("scopes") or {}).get(scope) or {}
        members = meta.get("members") or {}
        now = time.time()
        min_fam = int(self._cfg("gossip_min_familiarity", 68))
        active_days = float(self._cfg("gossip_active_days", 14))
        pair = {cand.get("a"), cand.get("b")}
        choices = []
        for qq, name in members.items():
            qq = str(qq or "")
            if not qq.isdigit() or qq in pair:
                continue
            if bool(self._cfg("gossip_exclude_admins", False)) and (
                self._is_admin_qq(qq)
            ):
                continue
            state = self._user_state(qq)
            umo = str(state.get("last_private_umo") or "")
            if ":FriendMessage:" not in umo or umo.startswith("webchat:"):
                continue
            last_seen = float(state.get("last_seen_ts") or 0)
            if not last_seen or now - last_seen > active_days * 86400:
                continue
            md = ""
            try:
                with open(self._profile_path(qq), encoding="utf-8") as f:
                    md = f.read()
            except Exception:
                md = ""
            fam_score, _, _, _, _, _ = self._familiarity_of(qq, md)
            if fam_score < min_fam:
                continue
            choices.append(
                {
                    "qq": qq,
                    "name": name or state.get("last_name") or qq,
                    "umo": umo,
                    "score": fam_score,
                }
            )
        if not choices:
            return None
        choices.sort(key=lambda item: item["score"], reverse=True)
        return random.choice(choices[:3])

    def _display_name(self, qq: str) -> str:
        try:
            with open(self._profile_path(qq), encoding="utf-8") as f:
                name = str(parse_profile(f.read()).get("name") or "").strip()
            if name:
                return name
        except Exception:
            pass
        return str(self._user_state(qq).get("last_name") or qq)

    async def _gossip_question(self, cand: dict, target: dict) -> str:
        names = cand.get("names") or {}
        a_name = str(names.get(cand.get("a")) or self._display_name(cand["a"]))
        b_name = str(names.get(cand.get("b")) or self._display_name(cand["b"]))
        rtype = str(cand.get("type") or "朋友")
        provider = None
        try:
            provider = await self.context.get_using_provider_async(
                umo=target["umo"]
            )
            if provider is None:
                provider = await self.context.get_using_provider_async()
        except Exception:
            provider = None
        if provider is None:
            return gossip_fallback_question(a_name, b_name, rtype)
        prompt = build_gossip_prompt(
            target.get("name") or target["qq"],
            a_name,
            b_name,
            rtype,
            str(cand.get("reason") or cand.get("evidence") or ""),
        )
        persona_prompt = ""
        try:
            persona = await self.context.persona_manager.get_persona(
                str(self._cfg("proactive_persona_id", "小雪"))
            )
            persona_prompt = str(getattr(persona, "system_prompt", "") or "")
        except Exception:
            persona_prompt = (
                "你是一个大学生妹妹，叫小雪，用第一人称、口语，像平时 QQ 聊天一样。"
            )
        kwargs = {"prompt": prompt}
        if persona_prompt:
            kwargs["system_prompt"] = persona_prompt
        try:
            result = await asyncio.wait_for(
                provider.text_chat(**kwargs), timeout=45
            )
            text = str(getattr(result, "completion_text", "") or "").strip()
        except Exception:
            text = ""
        text = text.splitlines()[0].strip().strip("“”\"'") if text else ""
        if not text:
            return gossip_fallback_question(a_name, b_name, rtype)
        return text[:80]

    async def _gossip_tick(self) -> None:
        if not self._enabled() or not bool(
            self._cfg("relation_enabled", True)
        ):
            return
        if not bool(self._cfg("gossip_enabled", True)):
            return
        now = time.time()
        if not self._gossip_window_ok(now) or not self._gossip_budget_ok(now):
            return
        if random.random() > max(
            0.0, min(1.0, float(self._cfg("gossip_chance", 0.5)))
        ):
            return
        candidates = gossip_candidates(
            self._relations(),
            now,
            min_confidence=float(
                self._cfg("gossip_min_suspect_confidence", 0.5)
            ),
            ttl_days=float(self._cfg("gossip_suspect_ttl_days", 30)),
            max_asks=max(1, int(self._cfg("gossip_max_asks_per_suspect", 1))),
            half_life_days=float(self._cfg("relation_half_life_days", 180)),
        )
        for cand in candidates:
            target = self._gossip_target(cand)
            if target is None:
                continue
            text = await self._gossip_question(cand, target)
            if not text or not await self._send_proactive(target["umo"], text):
                continue
            with self._rel_lock:
                relations = self._relations()
                edge = find_relation_edge(
                    relations.get("edges") or [], cand["a"], cand["b"]
                )
                if edge is not None:
                    entry = (edge.get("suspects") or {}).get(cand["type"])
                    if entry is not None:
                        entry.setdefault("asked", []).append(
                            {"target": target["qq"], "time": now}
                        )
                self._save_relations()
            gossip = self._load_state().setdefault("gossip", {})
            gossip["last_ts"] = now
            gossip["count"] = int(gossip.get("count") or 0) + 1
            self._save_state()
            logger.info(
                f"[{NAME}] 向 {target['name']} 打听 "
                f"{cand['a']} 和 {cand['b']} 的 {cand['type']} 猜测"
            )
            return

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
        recipient = str(umo or "").rsplit(":", 1)[-1]
        if not self._is_admin_qq(recipient):
            text = redact_ids(text, self._known_ids() | {recipient})
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
        md = ""
        try:
            with open(self._profile_path(qq), encoding="utf-8") as f:
                md = f.read()
        except Exception:
            md = ""
        ids = self._known_ids() | {qq}
        if md:
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
            summary = redact_ids(
                profile_summary(md, int(self._cfg("inject_limit_chars", 400))),
                ids,
            )
            familiarity = (
                f"\n\n[熟悉度] {fam_level}（{fam_score}/100；聊过 {exchanges} 次、"
                f"活跃 {active_days} 天；印象 {impression}、道德 {moral}）："
                f"{familiarity_guidance(fam_level)}"
            )
            req.system_prompt = prompt + "\n\n" + summary + familiarity
            if level != "正常":
                block = redact_ids(
                    moral_injection(
                        md, level, int(self._cfg("inject_limit_chars", 400))
                    ),
                    ids,
                )
                req.system_prompt += "\n\n" + block
        if bool(self._cfg("relation_enabled", True)):
            umo = str(event.unified_msg_origin or "")
            if umo and not umo.startswith("webchat:") and (
                ":GroupMessage:" in umo or ":FriendMessage:" in umo
            ):
                visible = {qq} | {
                    str(row.get("sender") or "")
                    for row in self._rel_buffers.get(umo, [])[-80:]
                    if row.get("sender")
                }
                block = relation_injection(
                    self._relations(),
                    visible,
                    time.time(),
                    focus_id=qq,
                    max_edges=int(self._cfg("relation_inject_max_edges", 6)),
                    limit=int(self._cfg("relation_inject_limit_chars", 400)),
                    half_life_days=float(
                        self._cfg("relation_half_life_days", 180)
                    ),
                )
                if block and RELATION_MARK not in req.system_prompt:
                    req.system_prompt += "\n\n" + redact_ids(block, ids)
        if SHARED_MARK not in req.system_prompt:
            shared = redact_ids(self._shared_injection(event, qq, req), ids)
            if shared:
                req.system_prompt += "\n\n" + shared

    # ---------------- 出站隐私兜底 ----------------
    def _known_ids(self) -> set[str]:
        owner = ""
        try:
            owner = str(self._cfg("owner_session", "") or "").rsplit(":", 1)[-1]
        except Exception:
            owner = ""
        admins: list[str] = []
        try:
            admins = [str(x) for x in self.context.get_config().get("admins_id") or []]
        except Exception:
            admins = []
        states = list((self._load_state().get("users") or {}).keys())
        profiles = [
            path.stem for path in Path(self._profiles_dir()).glob("*.md")
        ]
        return collect_ids(
            owner_qq=owner,
            admins=admins,
            profile_stems=profiles + states,
            relations=self._relations(),
            cards=self._shared().get("cards"),
            scopes=self._relations().get("scopes"),
        )

    def _id_map(self) -> dict[str, str]:
        owner = ""
        try:
            owner = str(self._cfg("owner_session", "") or "").rsplit(":", 1)[-1]
        except Exception:
            owner = ""
        profiles: dict[str, str] = {}
        try:
            for path in Path(self._profiles_dir()).glob("*.md"):
                try:
                    parsed = parse_profile(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                qq = str(parsed.get("qq") or path.stem)
                name = str(parsed.get("name") or "").strip()
                if qq.isdigit() and name:
                    profiles[qq] = name
        except Exception:
            pass
        for qq, state in (self._load_state().get("users") or {}).items():
            if isinstance(state, dict):
                name = str(state.get("last_name") or "").strip()
                if name:
                    profiles.setdefault(str(qq), name)
        try:
            for admin in self.context.get_config().get("admins_id") or []:
                profiles.setdefault(str(admin), "管理员")
        except Exception:
            pass
        return build_id_map(
            owner_qq=owner,
            owner_name="哥哥",
            profiles=profiles,
            relations=self._relations(),
            cards=self._shared().get("cards"),
            scopes=self._relations().get("scopes"),
        )

    @staticmethod
    def _sanitize_content(content, id_map: dict[str, str]):
        if isinstance(content, str):
            return sanitize_context_text(content, id_map)
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict):
                    item = dict(part)
                    if isinstance(item.get("text"), str):
                        item["text"] = sanitize_context_text(item["text"], id_map)
                    parts.append(item)
                else:
                    parts.append(part)
            return parts
        return content

    @filter.on_llm_request(priority=-(1 << 30))
    async def sanitize_llm_context(self, event: AstrMessageEvent, req):
        """在请求交给模型前，把上下文里的 QQ/群号替换成称呼。

        只处理这次请求的副本；画像、关系网、共享记忆文件里的原始数据不动。
        """
        if not self._enabled() or not bool(
            self._cfg("privacy_sanitize_context", True)
        ):
            return
        id_map = self._id_map()
        if not id_map:
            return
        if getattr(req, "system_prompt", ""):
            req.system_prompt = sanitize_context_text(req.system_prompt, id_map)
        contexts = getattr(req, "contexts", None)
        if isinstance(contexts, list):
            req.contexts = copy.deepcopy(contexts)
            for message in req.contexts:
                if isinstance(message, dict):
                    message["content"] = self._sanitize_content(
                        message.get("content"), id_map
                    )
        parts = getattr(req, "extra_user_content_parts", None)
        if isinstance(parts, list):
            req.extra_user_content_parts = copy.deepcopy(parts)
            for part in req.extra_user_content_parts:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    part["text"] = sanitize_context_text(part["text"], id_map)
                elif hasattr(part, "text") and isinstance(part.text, str):
                    part.text = sanitize_context_text(part.text, id_map)

    @filter.on_decorating_result(priority=1000)
    async def redact_outgoing_ids(self, event: AstrMessageEvent):
        """对非主人会话做兜底：回复里出现已知 QQ/群号就抹掉。"""
        if not self._enabled() or not bool(
            self._cfg("privacy_redact_ids", True)
        ):
            return
        if str(event.get_platform_name() or "") == "webchat":
            return
        umo = str(event.unified_msg_origin or "")
        is_group = "GroupMessage" in umo
        qq = str(getattr(event, "get_sender_id", lambda: "")() or "")
        if not is_group and self._is_admin_qq(qq):
            return
        result = event.get_result()
        if result is None or not getattr(result, "chain", None):
            return
        chain = result.chain
        if not isinstance(chain, list):
            chain = list(chain)
            result.chain = chain
        ids = self._known_ids() | {qq}
        changed = False
        for comp in chain:
            if not isinstance(comp, Plain):
                continue
            text = redact_ids(getattr(comp, "text", ""), ids)
            if text != getattr(comp, "text", ""):
                comp.text = text
                changed = True
        if changed:
            logger.info(f"[{NAME}] 已在出站消息中隐藏 QQ/群号（{umo}）")

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
        gossip_task = self._gossip_task
        if gossip_task is not None and not gossip_task.done():
            gossip_task.cancel()
            try:
                await gossip_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        self._gossip_task = None
        running = [t for t in self._profile_tasks if not t.done()]
        for t in running:
            t.cancel()
        if running:
            await asyncio.gather(*running, return_exceptions=True)
        self._profile_tasks.clear()
        self._tasks.clear()
        self._rel_tasks.clear()
        self._shared_tasks.clear()
        self._save_state()
