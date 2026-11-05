"""跨会话共享记忆的纯逻辑：卡片校验、可见性、检索与注入。"""

from __future__ import annotations

import re
import time

SHARED_MARK = "[共享记忆]"
SHARE_LEVELS = (0, 1, 2, 3)
_NOISE_RE = re.compile(r"[\s，。！？、,.!?\"'“”‘’：:；;（）()\[\]【】<>《》~～…\-]")


def _clean_text(text: str, limit: int) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip().strip("\"'“”‘’ ")
    if len(value) > limit:
        value = value[: max(1, limit - 1)].rstrip("，。！？；：,.!?;: ") + "…"
    return value


def card_key(summary: str) -> str:
    return _NOISE_RE.sub("", str(summary or "")).casefold()


def parse_cards_payload(text: str) -> list[dict]:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    start, end = raw.find("["), raw.rfind("]")
    if start >= 0 and end > start:
        try:
            data = __import__("json").loads(raw[start : end + 1])
            if isinstance(data, list):
                return [item for item in data if isinstance(item, dict)]
        except Exception:
            pass
    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        try:
            data = __import__("json").loads(raw[start : end + 1])
        except Exception:
            return []
        items = data.get("cards") if isinstance(data, dict) else None
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    return []


def clean_card(
    raw: dict,
    participants: set[str],
    max_summary: int = 180,
) -> dict | None:
    summary = _clean_text(raw.get("summary"), max_summary)
    if len(summary) < 4:
        return None
    try:
        level = int(raw.get("share_level", 2))
    except (TypeError, ValueError):
        level = 2
    level = max(0, min(3, level))
    # 兜底：即使模型给了高分享级别，命中明确敏感词也只按私密处理
    sensitive = (
        "密码", "验证码", "身份证", "银行卡", "工资", "收入",
        "病历", "怀孕", "抑郁", "自杀", "裸照", "私密", "别告诉",
    )
    if any(word in summary for word in sensitive):
        level = min(level, 1)
    topics = []
    for item in raw.get("topics") or []:
        value = _clean_text(item, 24)
        if value and value not in topics:
            topics.append(value)
        if len(topics) >= 6:
            break
    subjects = []
    for item in raw.get("subjects") or []:
        qq = str(item or "").strip()
        if qq.isdigit() and qq in participants and qq not in subjects:
            subjects.append(qq)
        if len(subjects) >= 8:
            break
    reason = _clean_text(raw.get("reason"), 80)
    return {
        "summary": summary,
        "topics": topics,
        "subjects": subjects,
        "share_level": level,
        "reason": reason,
    }


def merge_cards(
    cards: list[dict],
    new_cards: list[dict],
    source: dict,
    now: float | None = None,
    cap: int = 500,
) -> int:
    """把新卡片合并进全局列表；同摘要去重，保留最新来源。"""
    now = float(now if now is not None else time.time())
    changed = 0
    index = {card_key(card.get("summary")): card for card in cards or []}
    for raw in new_cards or []:
        key = card_key(raw.get("summary"))
        if not key:
            continue
        card = index.get(key)
        if card is None:
            card = {
                "id": f"{int(now)}-{len(cards) + changed}",
                "summary": raw["summary"],
                "topics": list(raw.get("topics") or []),
                "subjects": list(raw.get("subjects") or []),
                "share_level": int(raw.get("share_level") or 2),
                "reason": str(raw.get("reason") or ""),
                "source_scope": str(source.get("scope") or ""),
                "source_kind": str(source.get("kind") or ""),
                "source_label": str(source.get("label") or ""),
                "public_label": str(source.get("public_label") or ""),
                "created_at": now,
                "updated_at": now,
            }
            cards.append(card)
            index[key] = card
        else:
            card["updated_at"] = now
            card["source_scope"] = str(source.get("scope") or card.get("source_scope") or "")
            card["source_kind"] = str(source.get("kind") or card.get("source_kind") or "")
            card["source_label"] = str(source.get("label") or card.get("source_label") or "")
            card["public_label"] = str(
                source.get("public_label") or card.get("public_label") or ""
            )
            if raw.get("share_level") is not None:
                card["share_level"] = int(raw.get("share_level") or 2)
        changed += 1
    if cap > 0 and len(cards) > cap:
        cards.sort(key=lambda item: float(item.get("updated_at") or 0))
        del cards[: len(cards) - cap]
    return changed


def load_relation_index(data: dict) -> dict[tuple[str, str], float]:
    """把关系网文件转成 (a,b) → 最高置信度；兼容旧的 groups 结构。"""
    index: dict[tuple[str, str], float] = {}
    edges = []
    if isinstance(data, dict):
        edges = list(data.get("edges") or [])
        for group in (data.get("groups") or {}).values():
            if isinstance(group, dict):
                edges.extend(group.get("edges") or [])
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        a = str(edge.get("a") or "")
        b = str(edge.get("b") or "")
        if not a or not b:
            continue
        best = 0.0
        for entry in (edge.get("types") or {}).values():
            try:
                best = max(best, float(entry.get("confidence") or 0))
            except (TypeError, ValueError):
                continue
        if best:
            key = (a, b) if a <= b else (b, a)
            index[key] = max(index.get(key, 0.0), best)
    return index


def relation_confidence(index: dict, a: str, b: str) -> float:
    a, b = str(a or ""), str(b or "")
    if not a or not b:
        return 0.0
    key = (a, b) if a <= b else (b, a)
    return float(index.get(key, 0.0))


def _bigrams(text: str) -> set[str]:
    value = re.sub(r"\s+", "", str(text or ""))
    if len(value) < 2:
        return {value} if value else set()
    return {value[i : i + 2] for i in range(len(value) - 1)}


def card_relevance(card: dict, query: str) -> float:
    q = _bigrams(query)
    if not q:
        return 0.0
    text = " ".join(
        [str(card.get("summary") or "")]
        + [str(topic) for topic in card.get("topics") or []]
    )
    c = _bigrams(text)
    return len(q & c) / max(1, len(q))


def can_share(
    card: dict,
    audience: dict,
    relation_index: dict | None = None,
    min_confidence: float = 0.6,
) -> bool:
    """按分享评级和当前听众决定这张卡片能不能被提起。"""
    try:
        level = int(card.get("share_level") or 0)
    except (TypeError, ValueError):
        level = 0
    if level <= 0:
        return False
    if audience.get("is_owner"):
        return True
    if level >= 3:
        return True
    sender = str(audience.get("sender") or "")
    subjects = {str(qq) for qq in card.get("subjects") or [] if str(qq)}
    if sender and sender in subjects:
        return True
    if str(card.get("source_scope") or "") == str(audience.get("scope") or ""):
        return True
    if level <= 1:
        return False
    # level 2：只有当事人/同群成员/与当事人有明确关系的人才能听
    if not subjects:
        return False
    if audience.get("is_group"):
        members = {str(qq) for qq in audience.get("group_members") or []}
        return bool(members) and subjects <= members
    index = relation_index or {}
    return any(
        relation_confidence(index, sender, subject) >= min_confidence
        for subject in subjects
    )


def _recency_score(card: dict, now: float) -> float:
    try:
        stamp = float(card.get("updated_at") or card.get("created_at") or 0)
    except (TypeError, ValueError):
        stamp = 0.0
    if not stamp:
        return 0.0
    days = max(0.0, (float(now) - stamp) / 86400.0)
    return 1.0 / (1.0 + days / 14.0)


def select_cards(
    cards: list[dict],
    query: str,
    audience: dict,
    relation_index: dict | None,
    now: float | None = None,
    top_k: int = 4,
    min_score: float = 0.15,
    min_confidence: float = 0.6,
) -> list[dict]:
    now = float(now if now is not None else time.time())
    sender = str(audience.get("sender") or "")
    group_members = {str(qq) for qq in audience.get("group_members") or []}
    scored = []
    for card in cards or []:
        if str(card.get("source_scope") or "") == str(audience.get("scope") or ""):
            continue
        if not can_share(card, audience, relation_index, min_confidence):
            continue
        relevance = card_relevance(card, query)
        subjects = {str(qq) for qq in card.get("subjects") or []}
        subject_hit = 1.0 if (
            (sender and sender in subjects) or (group_members & subjects)
        ) else 0.0
        score = 0.6 * relevance + 0.25 * subject_hit + 0.15 * _recency_score(card, now)
        if score < min_score:
            continue
        scored.append((score, card))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [card for _, card in scored[: max(1, int(top_k))]]


def format_shared_block(
    cards: list[dict],
    audience: dict,
    limit: int = 600,
) -> str:
    if not cards:
        return ""
    lines = []
    for card in cards:
        label = (
            str(card.get("source_label") or "")
            if audience.get("is_owner")
            else str(card.get("public_label") or "另一个对话")
        )
        stamp = ""
        try:
            stamp = time.strftime(
                "%m-%d", time.localtime(float(card.get("updated_at") or 0))
            )
        except Exception:
            stamp = ""
        where = f"{label} · {stamp}" if stamp else label
        lines.append(f"- （{where}）{card.get('summary')}")
    head = (
        f"{SHARED_MARK} 这些是我在别的对话里记得的事（来源写在括号里）。"
        "只在自然相关时提起；不要主动说“另一个聊天”，不要复述隐私细节，"
        "不确定就不提。"
    )
    text = head + "\n" + "\n".join(lines)
    if limit > 0 and len(text) > limit:
        text = text[:limit] + "…"
    return text


def build_card_prompt(scope_label: str, exchanges: list[dict]) -> str:
    lines = []
    for item in exchanges[-16:]:
        lines.append(
            f"对方：{item.get('user') or ''}\n我：{item.get('assistant') or ''}"
        )
    convo = "\n\n".join(lines) or "（暂无对话）"
    return (
        f"你正在整理自己的「共享记忆卡片」，来源是：{scope_label or '一个对话'}。\n"
        "根据下面的对话，提取 0~3 条以后在别的对话里可能用得上的事。\n"
        "要求：\n"
        "- summary：第一人称、1~2 句、不超过 80 字；只写真实发生的事，不编造；"
        "不要写 QQ 号、群号、文件路径或系统提示；\n"
        "- topics：2~5 个关键词；subjects：涉及的对话参与者 QQ 号，只能从下面出现的人里选；\n"
        "- share_level：0=绝密（密码、健康、证件、财务等，任何时候都不要提）；"
        "1=只适合当事人/主人知道；2=和当事人有关系的人可以知道；"
        "3=任何聊天都可以自然提起；\n"
        "- reason：为什么这样分级；\n"
        "- 没有值得记的就输出空数组 []。\n"
        '只输出 JSON 数组：[{"summary":"...","topics":["..."],'
        '"subjects":["123456"],"share_level":2,"reason":"..."}]\n\n'
        f"对话：\n{convo}"
    )
