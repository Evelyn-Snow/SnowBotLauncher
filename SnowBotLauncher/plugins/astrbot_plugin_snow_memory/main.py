"""小雪全局记忆层：事件 → 事实 → 洞察，按听众检索。

和现有插件的关系：

- 全量采集所有会话（私聊/群聊/真实经历），写入 append-only 的事件账本；
- 夜间增量抽取结构化的 subject-predicate-object 事实，带双时间轴、
  置信度、隐私级别和证据；
- 事实足够多时归纳带证据的洞察；
- 聊天时按当前听众过滤后注入少量事实/洞察，避免把 A 的私事说给 B。

Phase 1+2 的骨架：insights_enabled / profile_render_enabled 可单独关闭。
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools
from astrbot.core.config.astrbot_config import AstrBotConfig

from .library import (
    FUNCTIONAL_PREDICATES,
    audience_visible,
    build_extraction_prompt,
    build_insight_prompt,
    content_similarity,
    cosine,
    extract_json_object,
    fact_search_text,
    normalize_text,
    parse_date,
    render_memory_block,
    score_candidate,
    sha1_text,
    should_recall,
    text_similarity,
    validate_fact,
    validate_insight,
)
from .store import MemoryStore

NAME = "astrbot_plugin_snow_memory"
MEMORY_MARK = "[记忆]"
EXTRACTOR_VERSION = "v1"


class SnowMemory(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.conf = config
        self._store: MemoryStore | None = None
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._last_extract = 0.0
        self._last_reflect = 0.0
        self._alias_cache: dict[str, str] | None = None
        self._alias_cache_at = 0.0

    # ---------------- 配置 ----------------
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

    def _store_obj(self) -> MemoryStore:
        if self._store is None:
            self._store = MemoryStore(self._data_dir() / "memory.db")
        return self._store

    def _aliases(self) -> dict[str, str]:
        now = time.time()
        if self._alias_cache is not None and now - self._alias_cache_at < 600:
            return self._alias_cache
        aliases: dict[str, str] = {}
        profile_dir = Path(
            str(self._cfg("profile_dir", r"C:\Evelyn_Snow\画像") or "")
        )
        try:
            for path in profile_dir.glob("*.md"):
                text = path.read_text(encoding="utf-8-sig")
                qq_match = re.search(r"^qq:\s*\"?([0-9]{5,12})\"?", text, re.M)
                name_match = re.search(r"^昵称:\s*(.+)$", text, re.M)
                qq = qq_match.group(1) if qq_match else ""
                nickname = name_match.group(1).strip() if name_match else ""
                canonical = nickname or qq
                if not canonical:
                    continue
                if qq:
                    aliases[qq] = canonical
                if nickname:
                    aliases[nickname] = canonical
        except Exception:
            pass
        owner = str(self._cfg("owner_name", "") or "").strip()
        owner_qq = str(self._cfg("owner_qq", "") or "").strip()
        bot = str(self._cfg("bot_name", "") or "").strip() or "小雪"
        for name in (owner, "哥哥", "主人", owner_qq, "回眸一号"):
            if name:
                aliases[name] = "哥哥"
        for name in (bot, "我", "小雪", "千秋雪", "Evelyn", "Evelyn Snow"):
            if name:
                aliases[name] = "小雪"
        self._alias_cache = aliases
        self._alias_cache_at = now
        return aliases

    # ---------------- 模型 / 向量 ----------------
    async def _provider(self, umo: str = ""):
        try:
            provider = await self.context.get_using_provider_async(umo=umo)
        except Exception:
            provider = None
        if provider is None:
            try:
                provider = await self.context.get_using_provider_async()
            except Exception:
                provider = None
        return provider

    def _embedding_provider(self):
        try:
            providers = self.context.get_all_embedding_providers()
        except Exception:
            return None
        wanted = str(self._cfg("embedding_provider_id", "") or "").strip()
        for provider in providers or []:
            if provider is None:
                continue
            try:
                provider_id = str((getattr(provider, "provider_config", {}) or {}).get("id") or "")
            except Exception:
                provider_id = ""
            if wanted and provider_id == wanted:
                return provider
        for provider in providers or []:
            if provider is not None and getattr(provider, "enabled", True):
                return provider
        return providers[0] if providers else None

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        provider = self._embedding_provider()
        if provider is None or not texts:
            return []
        try:
            vectors = await provider.get_embeddings(texts)
            return [list(map(float, vector)) for vector in (vectors or [])]
        except Exception as exc:
            logger.warning(f"[{NAME}] 向量化失败：{exc}")
            return []

    # ---------------- 事件采集 ----------------
    def _is_owner(self, event: AstrMessageEvent) -> bool:
        try:
            if event.role == "admin":
                return True
        except Exception:
            pass
        sender = str(getattr(event, "get_sender_id", lambda: "")() or "")
        if not sender:
            return False
        try:
            admins = {str(item) for item in self.context.get_config().get("admins_id") or []}
        except Exception:
            admins = set()
        return sender in admins

    def _audience(self, event: AstrMessageEvent) -> dict:
        sender_id = str(getattr(event, "get_sender_id", lambda: "")() or "")
        sender_name = ""
        try:
            sender_name = str(event.get_sender_name() or "").strip()
        except Exception:
            pass
        return {
            "is_owner": self._is_owner(event),
            "sender_id": sender_id,
            "sender_name": sender_name,
            "scope": str(event.unified_msg_origin or ""),
            "is_group": not event.is_private_chat(),
        }

    @filter.on_llm_response(priority=100002)
    async def capture_exchange(self, event: AstrMessageEvent, resp):
        if not self._enabled() or not bool(self._cfg("capture_enabled", True)):
            return
        user_text = str(getattr(event, "message_str", "") or "").strip()
        user_text = re.sub(r"\[At:[^\]]+\]", "", user_text).strip()
        reply_text = str(getattr(resp, "completion_text", "") or "").strip()
        # 表情包/表情标记不是她说的话，别让它们变成“事实”。
        reply_text = re.sub(r"&&[^&\r\n]{1,40}&&", "", reply_text)
        reply_text = re.sub(r"\[表情:[^\]]+\]", "", reply_text)
        reply_text = reply_text.replace("[[对话结束]]", "").strip()
        if not user_text or not reply_text:
            return
        if user_text.startswith(("/", "！", "!")):
            return
        platform = str(event.get_platform_name() or "")
        if platform == "webchat" and not bool(self._cfg("include_webchat", False)):
            return
        is_group = not event.is_private_chat()
        if is_group and not bool(self._cfg("include_groups", True)):
            return
        sender_id = str(getattr(event, "get_sender_id", lambda: "")() or "")
        if not sender_id:
            return
        sender_name = ""
        try:
            sender_name = str(event.get_sender_name() or "").strip()
        except Exception:
            pass
        if is_group:
            # group_chat_plus 会在 message_str 前加 “[时间] 昵称(ID:xxx): ”，
            # 抽取事实时不能把时间和 ID 当成正文。
            match = re.match(
                r"^\[[^\]]+\]\s*(?P<name>.+?)\(ID:(?P<id>\d+)\)"
                r"(?:\[[^\]]*\][^:]*)?:\s*(?P<text>.*)$",
                user_text,
                re.S,
            )
            if match:
                sender_name = match.group("name").strip() or sender_name
                sender_id = match.group("id") or sender_id
                user_text = match.group("text").strip()
        umo = str(event.unified_msg_origin or "")
        message_id = str(getattr(getattr(event, "message_obj", None), "message_id", "") or "")
        ts = float(
            getattr(getattr(event, "message_obj", None), "timestamp", 0)
            or getattr(event, "created_at", 0)
            or time.time()
        )
        privacy = 3 if is_group else 4
        try:
            self._store_obj().add_event(
                event_key=f"chat:{umo}:{message_id or ts}:user:{sha1_text(user_text)}",
                ts=ts,
                umo=umo,
                platform=platform,
                sender_id=sender_id,
                sender_name=sender_name,
                role="user",
                text=user_text[:1200],
                message_id=message_id,
                source="chat",
                privacy=privacy,
                meta={"group": is_group},
            )
            self._store_obj().add_event(
                event_key=f"chat:{umo}:{message_id or ts}:assistant:{sha1_text(reply_text)}",
                ts=time.time(),
                umo=umo,
                platform=platform,
                sender_id=str(getattr(event, "get_self_id", lambda: "")() or ""),
                sender_name=str(self._cfg("bot_name", "小雪") or "小雪"),
                role="assistant",
                text=reply_text[:1600],
                message_id=message_id,
                source="chat",
                privacy=privacy,
                meta={"group": is_group},
            )
        except Exception as exc:
            logger.warning(f"[{NAME}] 事件写入失败：{exc}")

    # ---------------- 真实经历入账 ----------------
    async def _ingest_experience(self) -> int:
        try:
            path = Path(str(StarTools.get_data_dir("astrbot_plugin_snow_experience"))) / "experience_state.json"
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            return 0
        records = data.get("records") if isinstance(data, dict) else None
        if not isinstance(records, list):
            return 0
        added = 0
        store = self._store_obj()
        for record in records[-40:]:
            if not isinstance(record, dict):
                continue
            title = str(record.get("title") or "").strip()
            gist = str(record.get("gist") or "").strip()
            if not title and not gist:
                continue
            date_text = str(record.get("date") or "")
            ts = parse_date(date_text, time.time())
            text = f"{title}：{gist}".strip("：")
            key = f"exp:{date_text}:{record.get('type')}:{sha1_text(title + '|' + gist)}"
            if store.add_event(
                event_key=key,
                ts=ts,
                umo="experience:global",
                platform="experience",
                sender_id="",
                sender_name="我",
                role="experience",
                text=text[:1200],
                source="experience",
                privacy=3,
                meta={"event_type": record.get("type"), "title": title},
            ):
                added += 1
        return added

    # ---------------- 抽取 ----------------
    async def _extract_pending(self) -> None:
        if self._lock.locked():
            return
        async with self._lock:
            store = self._store_obj()
            batch = max(4, int(self._cfg("extract_batch_size", 24) or 24))
            events = store.pending_events(batch)
            if not events:
                return
            provider = await self._provider()
            if provider is None:
                logger.info(f"[{NAME}] 没有可用模型，跳过抽取")
                return
            prompt = build_extraction_prompt(events)
            try:
                result = await asyncio.wait_for(
                    provider.text_chat(
                        prompt=prompt,
                        system_prompt="你是记忆整理器。只输出 JSON，不要解释。",
                    ),
                    timeout=90,
                )
            except Exception as exc:
                logger.warning(f"[{NAME}] 事实抽取失败，稍后重试：{exc}")
                store.bump_attempts([event["id"] for event in events])
                return
            data = extract_json_object(str(getattr(result, "completion_text", "") or ""))
            if not data:
                store.bump_attempts([event["id"] for event in events])
                logger.info(f"[{NAME}] 抽取结果不是 JSON，稍后重试")
                return

            events_text = "\n".join(str(event.get("text") or "") for event in events)
            aliases = self._aliases()
            raw_facts = data.get("facts") if isinstance(data.get("facts"), list) else []
            inserted: list[tuple[int, str]] = []
            for raw in raw_facts:
                source_event = self._source_event(events, raw.get("evidence"))
                default_ts = float(source_event.get("ts") or time.time())
                max_privacy = 3 if source_event.get("source") in ("experience",) or self._is_group_event(source_event) else 4
                fact = validate_fact(
                    raw,
                    events_text=events_text,
                    default_ts=default_ts,
                    max_privacy=max_privacy,
                    aliases=aliases,
                    extractor_version=EXTRACTOR_VERSION,
                )
                if fact is None:
                    continue
                fact["scope"] = str(source_event.get("umo") or "")
                # 主人在群里说的事，同群可见；主人在私聊说的事，只在私聊可见。
                if fact.get("subject_key") == "哥哥":
                    in_group = self._is_group_event(source_event) or ":GroupMessage:" in fact["scope"]
                    fact["privacy"] = 3 if in_group else 1
                fact["source_event_ids"] = [int(source_event["id"])]
                fact["search_text"] = fact_search_text(fact)
                fact["meta"] = {"reason": str(raw.get("reason") or "")[:200]}
                fact_id = self._insert_fact_with_conflicts(fact)
                if fact_id:
                    inserted.append((fact_id, fact["search_text"]))
            if inserted:
                vectors = await self._embed([text for _, text in inserted])
                for (fact_id, _), vector in zip(inserted, vectors):
                    store.set_fact_embedding(fact_id, vector)
            store.mark_processed([int(event["id"]) for event in events])
            self._last_extract = time.time()
            logger.info(
                f"[{NAME}] 抽取 {len(events)} 条事件 → {len(inserted)} 条事实"
            )

    @staticmethod
    def _is_group_event(event: dict) -> bool:
        try:
            meta = json.loads(event.get("meta") or "{}")
        except Exception:
            meta = {}
        return bool(meta.get("group"))

    @staticmethod
    def _source_event(events: list[dict], evidence) -> dict:
        needle = normalize_text(str(evidence or ""))
        if needle:
            for event in events:
                if needle in normalize_text(str(event.get("text") or "")):
                    return event
        return events[-1]

    def _insert_fact_with_conflicts(self, fact: dict) -> int | None:
        store = self._store_obj()
        existing = store.find_active(fact["subject_key"], fact["predicate"])
        for old in existing:
            if (
                old.get("object_key") == fact.get("object_key")
                and int(old.get("polarity") or 1) == int(fact.get("polarity") or 1)
            ):
                for event_id in fact.get("source_event_ids") or []:
                    store.add_fact_source(int(old["id"]), int(event_id))
                return None
        new_id = store.add_fact(fact)
        # 功能性谓词（住在哪/做什么/年龄/生日/状态）出现新值：旧值失效；
        # 同一对象出现相反极性（喜欢↔不喜欢）也以新说法为准。
        should_supersede = fact["predicate"] in FUNCTIONAL_PREDICATES
        if not should_supersede:
            should_supersede = any(
                old.get("object_key") == fact.get("object_key")
                and int(old.get("polarity") or 1) != int(fact.get("polarity") or 1)
                for old in existing
            )
        if should_supersede:
            for old in existing:
                try:
                    store.supersede_fact(
                        int(old["id"]),
                        new_id,
                        valid_to=float(fact.get("valid_from") or time.time()),
                    )
                except Exception:
                    pass
        return new_id

    # ---------------- 反思 / 洞察 ----------------
    async def _reflect(self) -> None:
        if not bool(self._cfg("insights_enabled", True)):
            return
        if self._lock.locked():
            return
        async with self._lock:
            store = self._store_obj()
            facts = store.active_facts(int(self._cfg("insight_max_facts", 600) or 600))
            min_facts = max(3, int(self._cfg("insight_min_facts", 6) or 6))
            if len(facts) < min_facts:
                return
            by_subject: dict[str, list[dict]] = {}
            for fact in facts:
                key = str(fact.get("subject_key") or "")
                if key:
                    by_subject.setdefault(key, []).append(fact)
            ranked = sorted(by_subject.items(), key=lambda item: len(item[1]), reverse=True)
            existing_insights = store.active_insights()
            inserted: list[tuple[int, str]] = []
            for subject, rows in ranked[: int(self._cfg("insight_max_subjects", 6) or 6)]:
                if len(rows) < 3:
                    continue
                subject_name = str(rows[0].get("subject") or subject)
                prompt = build_insight_prompt(subject_name, rows[:30])
                provider = await self._provider()
                if provider is None:
                    return
                try:
                    result = await asyncio.wait_for(
                        provider.text_chat(
                            prompt=prompt,
                            system_prompt="你是记忆归纳器。只输出 JSON，不要解释。",
                        ),
                        timeout=90,
                    )
                except Exception as exc:
                    logger.warning(f"[{NAME}] 洞察生成失败：{exc}")
                    continue
                data = extract_json_object(str(getattr(result, "completion_text", "") or ""))
                raw_insights = data.get("insights") if isinstance(data.get("insights"), list) else []
                fact_ids = {int(row["id"]) for row in rows}
                privacy_by_fact = {int(row["id"]): int(row.get("privacy") or 2) for row in rows}
                for raw in raw_insights:
                    if str(raw.get("insight_type") or "").strip().lower() == "preference":
                        continue
                    default_scope = "self" if subject in {"小雪", "千秋雪"} else f"other:{subject_name}"
                    insight = validate_insight(
                        raw,
                        fact_ids=fact_ids,
                        default_scope=default_scope,
                        aliases=self._aliases(),
                        min_evidence=int(self._cfg("insight_min_evidence", 3) or 3),
                    )
                    if insight is None:
                        continue
                    if default_scope == "self":
                        insight["scope"] = "self"
                    insight["privacy"] = min(
                        privacy_by_fact.get(fid, 2) for fid in insight["evidence_fact_ids"]
                    )
                    if any(
                        str(old.get("scope") or "") == insight["scope"]
                        and text_similarity(str(old.get("statement") or ""), insight["statement"]) > 0.82
                        for old in existing_insights
                    ):
                        continue
                    insight["search_text"] = insight["statement"]
                    insight_id = store.add_insight(insight)
                    inserted.append((insight_id, insight["search_text"]))
                    existing_insights.append(insight)
            if inserted:
                vectors = await self._embed([text for _, text in inserted])
                for (insight_id, _), vector in zip(inserted, vectors):
                    store.set_insight_embedding(insight_id, vector)
            store.set_meta("last_reflect", time.time())
            self._last_reflect = time.time()
            if inserted:
                logger.info(f"[{NAME}] 生成 {len(inserted)} 条洞察")

    # ---------------- 检索注入 ----------------
    @filter.on_llm_request(priority=-(1 << 30) - 50)
    async def inject_memory(self, event: AstrMessageEvent, req):
        if not self._enabled() or not bool(self._cfg("retrieve_enabled", True)):
            return
        try:
            prompt = str(getattr(req, "system_prompt", "") or "")
        except Exception:
            prompt = ""
        if MEMORY_MARK in prompt:
            return
        text = str(getattr(event, "message_str", "") or "").strip()
        if not text:
            return
        audience = self._audience(event)
        store = self._store_obj()
        facts = [fact for fact in store.active_facts() if audience_visible(fact, audience)]
        insights = [item for item in store.active_insights() if audience_visible(item, audience)]
        if not facts and not insights:
            if should_recall(text) and not bool(self._cfg("shadow_mode", False)):
                req.system_prompt = prompt + "\n\n" + render_memory_block([], [], abstain_hint=True)
            return

        query_vec: list[float] = []
        vectors = await self._embed([text])
        if vectors:
            query_vec = vectors[0]
        now = time.time()
        min_similarity = float(self._cfg("min_similarity", 0.1) or 0.1)
        fact_candidates = []
        for fact in facts:
            fact_text = str(fact.get("search_text") or "")
            content_sim = content_similarity(text, fact_text)
            similarity = content_sim
            if query_vec and fact.get("embedding"):
                try:
                    similarity = cosine(query_vec, json.loads(fact["embedding"]))
                except Exception:
                    similarity = content_sim
            # 字面撞不上时允许语义兜底，但阈值更高，避免只靠主语相关。
            if content_sim < min_similarity and similarity < float(
                self._cfg("min_embedding_similarity", 0.35) or 0.35
            ):
                continue
            score = score_candidate(fact, query=text, now=now, similarity=similarity)
            fact_candidates.append((score, fact))
        insight_candidates = []
        for insight in insights:
            statement = str(insight.get("statement") or "")
            content_sim = content_similarity(text, statement)
            similarity = content_sim
            if query_vec and insight.get("embedding"):
                try:
                    similarity = cosine(query_vec, json.loads(insight["embedding"]))
                except Exception:
                    similarity = content_sim
            if content_sim < min_similarity and similarity < float(
                self._cfg("min_embedding_similarity", 0.35) or 0.35
            ):
                continue
            score = score_candidate(insight, query=text, now=now, similarity=similarity)
            insight_candidates.append((score, insight))
        fact_candidates.sort(key=lambda item: item[0], reverse=True)
        insight_candidates.sort(key=lambda item: item[0], reverse=True)
        min_score = float(self._cfg("min_score", 0.15) or 0.15)
        top_facts = [item for score, item in fact_candidates if score >= min_score][
            : int(self._cfg("max_facts", 8) or 8)
        ]
        top_insights = [item for score, item in insight_candidates if score >= min_score][
            : int(self._cfg("max_insights", 3) or 3)
        ]
        block = render_memory_block(
            top_facts,
            top_insights,
            limit_chars=int(self._cfg("inject_limit_chars", 900) or 900),
            abstain_hint=should_recall(text) and not top_facts and not top_insights,
        )
        if not block:
            return
        if bool(self._cfg("shadow_mode", False)):
            logger.info(
                f"[{NAME}] 影子模式：命中 {len(top_facts)} 条事实 / {len(top_insights)} 条洞察，未注入"
            )
            return
        req.system_prompt = prompt + "\n\n" + block
        logger.info(
            f"[{NAME}] 注入 {len(top_facts)} 条事实 / {len(top_insights)} 条洞察"
        )

    # ---------------- 调度 ----------------
    async def _loop(self) -> None:
        while True:
            try:
                await self._ingest_experience()
                store = self._store_obj()
                pending = store.pending_events(1)
                due_extract = (
                    time.time() - self._last_extract
                    >= float(self._cfg("extract_interval_minutes", 30) or 30) * 60
                )
                if bool(self._cfg("extract_enabled", True)) and pending and (
                    store.event_count(0) >= int(self._cfg("extract_min_events", 6) or 6)
                    or due_extract
                ):
                    for _ in range(
                        max(1, int(self._cfg("extract_batches_per_run", 1) or 1))
                    ):
                        await self._extract_pending()
                        if not store.pending_events(1):
                            break
                due_reflect = (
                    time.time() - self._last_reflect
                    >= float(self._cfg("insight_interval_hours", 24) or 24) * 3600
                )
                if bool(self._cfg("insights_enabled", True)) and due_reflect:
                    await self._reflect()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(f"[{NAME}] 后台循环出错：{exc}")
            await asyncio.sleep(60)

    async def initialize(self) -> None:
        if not self._enabled():
            return
        self._store_obj()
        self._task = asyncio.create_task(self._loop())

    async def terminate(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        if self._store:
            self._store.close()
            self._store = None
