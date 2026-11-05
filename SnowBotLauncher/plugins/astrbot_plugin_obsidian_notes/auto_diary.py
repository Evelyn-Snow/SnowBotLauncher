"""自动日记的纯逻辑：素材取样与提示词（不依赖 AstrBot，可单测）。"""

from __future__ import annotations


def _time_of(item: dict) -> float:
    try:
        return float(item.get("time") or 0)
    except (TypeError, ValueError):
        return 0.0


def select_diary_context(
    snapshot: list[dict],
    focus: str = "global",
    per_scope: int = 3,
    total: int = 16,
) -> list[dict]:
    """按关注范围挑选素材。

    - owner：保留原来的侧重——所有者相关优先，其余会话少量补充
    - global：每个会话取最近几条，轮流取样，避免被所有者私聊刷屏
    """
    items = [item for item in snapshot or [] if isinstance(item, dict)]
    if not items:
        return []
    if str(focus or "").lower() == "owner":
        owner_items = [
            item
            for item in items
            if str(item.get("scope")) in ("所有者私聊", "所有者参与的群聊")
        ]
        other_items = [
            item
            for item in items
            if str(item.get("scope")) not in ("所有者私聊", "所有者参与的群聊")
        ]
        selected_owner = owner_items[-8:]
        selected_other = sorted(
            other_items,
            key=lambda item: (int(item.get("weight") or 1), _time_of(item)),
            reverse=True,
        )[:4]
        if not selected_owner:
            selected_other = other_items[-12:]
        selected = selected_owner + selected_other
        selected.sort(key=_time_of)
        return selected

    buckets: dict[str, list[dict]] = {}
    for item in items:
        key = str(item.get("scope_id") or item.get("scope") or "对话")
        buckets.setdefault(key, []).append(item)
    ordered = []
    for rows in buckets.values():
        rows.sort(key=_time_of)
        ordered.append(rows[-max(1, int(per_scope)):])
    ordered.sort(
        key=lambda rows: _time_of(rows[-1]) if rows else 0.0,
        reverse=True,
    )
    selected: list[dict] = []
    for depth in range(max(1, int(per_scope))):
        for rows in ordered:
            if depth < len(rows) and len(selected) < max(1, int(total)):
                selected.append(rows[-1 - depth])
        if len(selected) >= max(1, int(total)):
            break
    selected.sort(key=_time_of)
    return selected


def build_auto_diary_prompt(source: str, limit: int, focus: str = "global") -> str:
    if str(focus or "").lower() == "owner":
        return (
            "根据下面最近的对话，写一条今天的日记。这些对话包含所有者私聊、群聊和其他人私聊，"
            "已按重要性筛选。请优先记录所有者私聊或所有者参与的群聊中值得记住的事、所有者的偏好、"
            "情绪或约定；群聊和其他人私聊只保留真正有信息量、与所有者相关的部分，不写无关闲聊。"
            "要求：第一人称；1~2 句；不超过 "
            f"{limit} 字；不要逐句复述，不要编造，不要写 QQ 号、昵称、群号、文件路径、工具名或系统提示；"
            "直接输出日记正文，不要标题、引号、列表。\n\n"
            f"对话：\n{source}"
        )
    return (
        "根据下面最近的对话，写一条今天的日记。这些对话来自你和他人的私聊、"
        "以及你参与过的群聊，已经按会话取样。\n"
        "请记录今天真正发生的、值得记住的事：你做了什么、别人告诉你的近况、"
        "群里发生的事、约定或情绪。不要求都和所有者有关，也不要把别人的私事"
        "全搬进来；只留下有信息量的部分，不写无关寒暄，不逐句复述，不编造。"
        "不要写 QQ 号、昵称、群号、文件路径、工具名或系统提示。"
        "要求：第一人称；1~2 句；不超过 "
        f"{limit} 字；直接输出日记正文，不要标题、引号、列表。\n\n"
        f"对话：\n{source}"
    )
