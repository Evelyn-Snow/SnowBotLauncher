"""引用回复的搜索逻辑：在当前会话前文里找最相关的一句。

不依赖 AstrBot，可单独测试。历史记录由 main.py 维护，每条包含
id / umo / sender_id / sender_name / text / ts。
"""

from __future__ import annotations

import re

_PUNCT = re.compile(r"[\s，。！？、；：,.!?;:~～…“”\"'（）()【】\[\]]+")


def _normalize(text: str) -> str:
    return _PUNCT.sub("", str(text or "")).lower()


def _bigrams(text: str) -> set[str]:
    value = _normalize(text)
    if len(value) < 2:
        return {value} if value else set()
    return {value[i : i + 2] for i in range(len(value) - 1)}


def bigram_score(left: str, right: str) -> float:
    a, b = _bigrams(left), _bigrams(right)
    if not a or not b:
        return 0.0
    return len(a & b) / max(1, len(a | b))


def _quote_inside(text: str) -> str:
    match = re.search(r"[「“\"']([^」”\"']{2,})[」”\"']", str(text or ""))
    return match.group(1) if match else ""


def match_score(target: str, record_text: str) -> float:
    """目标描述/原话片段与历史消息的匹配分 0~1。"""
    target = str(target or "").strip()
    record_text = str(record_text or "").strip()
    if not target or not record_text:
        return 0.0
    quoted = _quote_inside(target)
    if quoted and quoted in record_text:
        return 0.98
    if target in record_text or record_text in target:
        return 0.92
    score = bigram_score(target, record_text)
    # 描述可能比原话长/短，用较短文本覆盖率补一点
    shorter, longer = sorted((_normalize(target), _normalize(record_text)), key=len)
    if shorter and len(shorter) >= 2:
        coverage = sum(1 for ch in set(shorter) if ch in longer) / len(set(shorter))
        score = max(score, coverage * 0.55)
    return min(1.0, score)


def search_quote_target(
    records: list[dict],
    target: str,
    current_id: str = "",
    *,
    now: float = 0.0,
    lookback_minutes: int = 720,
    lookback_messages: int = 200,
    min_message_distance: int = 4,
    min_time_distance_minutes: int = 10,
    threshold: float = 0.2,
) -> tuple[dict | None, str]:
    """在历史里找最相关且“足够远”的消息；返回 (记录, 原因/说明)。"""
    target = str(target or "").strip()
    if not target:
        return None, "没有给出要回复的内容"
    rows = [r for r in (records or []) if isinstance(r, dict)]
    if not rows:
        return None, "还没有可搜索的前文"
    current_index = -1
    for index in range(len(rows) - 1, -1, -1):
        if str(rows[index].get("id") or "") == str(current_id or ""):
            current_index = index
            break
    if current_index < 0:
        current_index = len(rows) - 1
    start = max(0, current_index - max(1, int(lookback_messages)))
    best = None
    best_score = 0.0
    close_best = None
    close_score = 0.0
    for index in range(start, current_index):
        record = rows[index]
        rid = str(record.get("id") or "")
        if not rid or rid == str(current_id or ""):
            continue
        ts = float(record.get("ts") or 0)
        if now and ts and now - ts > max(1, int(lookback_minutes)) * 60:
            continue
        score = match_score(target, str(record.get("text") or ""))
        if score < float(threshold):
            continue
        distance = current_index - index
        time_distance = (now - ts) if (now and ts) else 0.0
        far_enough = (
            distance >= max(1, int(min_message_distance))
            or (time_distance and time_distance >= max(1, int(min_time_distance_minutes)) * 60)
        )
        if not far_enough:
            if score > close_score:
                close_best, close_score = record, score
            continue
        if score > best_score:
            best, best_score = record, score
    if best is not None:
        return best, f"匹配度 {best_score:.2f}"
    if close_best is not None:
        return None, "目标离得太近，不需要引用；直接回答"
    return None, "前文里没找到足够明确的目标；不要强行引用"


def format_record(record: dict) -> str:
    import datetime as _dt

    ts = float(record.get("ts") or 0)
    when = (
        _dt.datetime.fromtimestamp(ts).strftime("%m-%d %H:%M") if ts else "未知时间"
    )
    name = str(record.get("sender_name") or record.get("sender_id") or "某人")
    text = str(record.get("text") or "").strip().replace("\n", " ")
    if len(text) > 100:
        text = text[:100] + "…"
    return f"[{when}] {name}：{text}"
