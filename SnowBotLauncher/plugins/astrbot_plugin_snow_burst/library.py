"""消息合流的纯逻辑：连续性评分、分组、历史 user 消息合并。

不依赖 AstrBot，全部可单测。
"""

from __future__ import annotations

import re

_END_PUNCT = "。！？!?…~～"
_FOLLOWUP_PREFIXES = (
    "那",
    "然后",
    "所以",
    "但是",
    "不过",
    "还有",
    "对了",
    "这个",
    "那个",
    "刚才",
    "咋",
    "怎么",
    "为什么",
)
_TOPIC_MARKERS = ("http", "b23.tv", "bilibili", "视频", "链接", "看看", "看这个")


def _clean(text: str) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def _bigrams(text: str) -> set[str]:
    value = _clean(text).lower()
    if len(value) < 2:
        return {value} if value else set()
    return {value[i : i + 2] for i in range(len(value) - 1)}


def continuity_score(prev: str, new: str) -> float:
    """0~1 的连续性评分：字面重合 + 追问/未说完/同话题信号。

    只用轻量特征，不调模型，单次微秒级，适合每来一条消息算一次。
    """
    a, b = _clean(prev), _clean(new)
    if not a or not b:
        return 0.0
    left, right = _bigrams(a), _bigrams(b)
    overlap = len(left & right) / max(1, len(left | right))
    score = min(0.55, overlap * 1.2)

    if b.startswith(_FOLLOWUP_PREFIXES):
        score += 0.18
    if len(b) <= 6:
        score += 0.12
    # 上一句没有句末标点，说明话还没说完
    if a[-1] not in _END_PUNCT:
        score += 0.12
    if any(k in a for k in _TOPIC_MARKERS) and any(k in b for k in _TOPIC_MARKERS):
        score += 0.15
    return min(1.0, score)


def should_extend(score: float, threshold: float = 0.18) -> bool:
    return float(score or 0) >= float(threshold or 0)


def merge_texts(texts: list[str]) -> str:
    """把同一组消息按顺序拼起来，去掉空项和相邻重复。"""
    out: list[str] = []
    for raw in texts or []:
        text = str(raw or "").strip()
        if not text:
            continue
        if out and out[-1] == text:
            continue
        out.append(text)
    return "\n".join(out)


def _content_parts(content) -> list[dict]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    if isinstance(content, list):
        return [dict(x) if isinstance(x, dict) else {"type": "text", "text": str(x)} for x in content]
    if content is None:
        return []
    return [{"type": "text", "text": str(content)}]


def merge_user_messages(left: dict, right: dict) -> dict:
    """合并两条相邻的 user 消息，保留非文本段（图片等）的顺序。"""
    merged_parts: list[dict] = []
    for part in _content_parts(left.get("content")) + _content_parts(right.get("content")):
        if (
            part.get("type") == "text"
            and merged_parts
            and merged_parts[-1].get("type") == "text"
        ):
            a = str(merged_parts[-1].get("text") or "").rstrip()
            b = str(part.get("text") or "").lstrip()
            merged_parts[-1]["text"] = (a + "\n" + b).strip()
        else:
            merged_parts.append(part)
    result = dict(left)
    result["role"] = "user"
    result["content"] = merged_parts
    return result


_SPEAKER_LABEL_RE = re.compile(r"^\[[^\]]+\]\s*[^\n:：]{1,80}[:：]")


def has_speaker_label(content) -> bool:
    """群聊历史里 AstrBot 会把每条写成 `[时间] 昵称(ID): 内容`。"""
    return isinstance(content, str) and bool(
        _SPEAKER_LABEL_RE.match(content.strip())
    )


def merge_contexts(
    contexts: list[dict],
    same_sender_only: bool = False,
    allow_labeled_cross_sender: bool = False,
) -> list[dict]:
    """把历史里连续的 user 消息并成一条，避免模型看到碎成好几轮的同一段话。

    - 私聊：直接合并
    - 群聊：默认只合并同一 name 的；开启 allow_labeled_cross_sender 后，
      两条都带 `[时间] 昵称:` 标签时也可以合并——标签本身会保留在文本里，
      不会把 A 的话算到 B 头上。
    """
    out: list[dict] = []
    for msg in contexts or []:
        if not isinstance(msg, dict):
            out.append(msg)
            continue
        if (
            msg.get("role") == "user"
            and out
            and isinstance(out[-1], dict)
            and out[-1].get("role") == "user"
        ):
            if same_sender_only:
                left_name = str(out[-1].get("name") or "")
                right_name = str(msg.get("name") or "")
                same_name = bool(left_name) and left_name == right_name
                labeled = (
                    allow_labeled_cross_sender
                    and has_speaker_label(out[-1].get("content"))
                    and has_speaker_label(msg.get("content"))
                )
                if not same_name and not labeled:
                    out.append(dict(msg))
                    continue
            out[-1] = merge_user_messages(out[-1], msg)
        else:
            out.append(dict(msg))
    return out


def group_parts(parts: list[dict], gap_seconds: float = 2.0, threshold: float = 0.18) -> list[list[dict]]:
    """按时间间隔和连续性把一次 burst 分成若干组。"""
    groups: list[list[dict]] = []
    current: list[dict] = []
    for part in parts or []:
        if not current:
            current = [part]
            continue
        prev = current[-1]
        gap = float(part.get("ts") or 0) - float(prev.get("ts") or 0)
        score = continuity_score(str(prev.get("text") or ""), str(part.get("text") or ""))
        if gap <= gap_seconds and (
            should_extend(score, threshold) or len(_clean(part.get("text"))) <= 6
        ):
            current.append(part)
        else:
            groups.append(current)
            current = [part]
    if current:
        groups.append(current)
    return groups


def chunk_parts(parts: list[dict], max_messages: int) -> list[list[dict]]:
    """组内再按条数切块，避免一次塞太多。"""
    size = max(1, int(max_messages or 1))
    return [list(parts[i : i + size]) for i in range(0, len(parts), size)]
