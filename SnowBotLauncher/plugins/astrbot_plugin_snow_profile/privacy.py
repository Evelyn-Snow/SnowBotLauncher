"""出站隐私兜底：把已知 QQ/群号从回复里抹掉。"""

from __future__ import annotations

import re

_PREFIXED_ID_RE = re.compile(
    r"(?:QQ|qq|Qq|群号|群号是|群号：|群号:|电话|手机号|手机|身份证)"
    r"([^0-9]{0,6})(\d{5,18})"
)
_MARKED_ID_RE = re.compile(
    r"[\(（]?(?i:ID)[:：]\s*\d{5,18}[\)）]?"
)
_NAMED_MARKED_ID_RE = re.compile(
    r"(\S+?)\s*[\(（](?i:ID)[:：]\s*\d{5,18}[\)）]"
)
def sanitize_context_text(text: str, id_map: dict[str, str] | None = None) -> str:
    """把上下文里的 QQ/群号换成称呼，保留可辨认性，不暴露数字。"""
    value = str(text or "")
    # “回眸一号(ID:123)” → “回眸一号”
    value = _NAMED_MARKED_ID_RE.sub(lambda match: match.group(1), value)
    # 单独的 (ID:123) → (某位群友)
    value = _MARKED_ID_RE.sub("（某位群友）", value)
    # “QQ号/群号/电话…”后面的数字直接隐藏
    value = _PREFIXED_ID_RE.sub(
        lambda match: match.group(0).replace(
            match.group(2), "（已隐藏）", 1
        ),
        value,
    )
    for qq, name in sorted(
        (id_map or {}).items(), key=lambda pair: len(str(pair[0])), reverse=True
    ):
        qq = str(qq)
        if qq and qq in value:
            value = re.sub(
                rf"(?<!\d){re.escape(qq)}(?!\d)",
                str(name or "一个朋友"),
                value,
            )
    return value


def redact_ids(text: str, ids: set[str] | list[str]) -> str:
    """把已知号码和带 QQ/群号/电话前缀的号码替换掉。"""
    value = str(text or "")
    for qq in sorted({str(item) for item in ids or [] if item}, key=len, reverse=True):
        if qq and qq in value:
            value = value.replace(qq, "（不方便说）")
    value = _PREFIXED_ID_RE.sub(
        lambda match: match.group(0).replace(
            match.group(2), "（不方便说）", 1
        ),
        value,
    )
    return value


def build_id_map(
    *,
    owner_qq: str = "",
    owner_name: str = "哥哥",
    profiles: dict[str, str] | None = None,
    relations: dict | None = None,
    cards: list[dict] | None = None,
    scopes: dict | None = None,
) -> dict[str, str]:
    """QQ/群号 → 上下文里使用的称呼。"""
    mapping: dict[str, str] = {}

    def add(qq: object, name: object) -> None:
        key = str(qq or "").strip()
        if key.isdigit():
            mapping[key] = str(name or mapping.get(key) or "一个朋友")

    add(owner_qq, owner_name or "哥哥")
    for qq, name in (profiles or {}).items():
        add(qq, name)
    for edge in (relations or {}).get("edges") or []:
        for qq, name in (edge.get("names") or {}).items():
            add(qq, name)
    for group in ((relations or {}).get("groups") or {}).values():
        for edge in (group or {}).get("edges") or []:
            for qq, name in (edge.get("names") or {}).items():
                add(qq, name)
    for card in cards or []:
        for subject in card.get("subjects") or []:
            add(subject, mapping.get(str(subject)) or "一个朋友")
    for umo in (scopes or {}):
        tail = str(umo).rsplit(":", 1)[-1]
        if tail.isdigit():
            mapping[tail] = "这个群"
    return mapping


def collect_ids(
    *,
    owner_qq: str = "",
    admins: list[str] | tuple[str, ...] = (),
    profile_stems: list[str] | tuple[str, ...] = (),
    relations: dict | None = None,
    cards: list[dict] | None = None,
    scopes: dict | None = None,
) -> set[str]:
    ids: set[str] = set()

    def add(value: object) -> None:
        text = str(value or "").strip()
        if text.isdigit() and 5 <= len(text) <= 18:
            ids.add(text)

    add(owner_qq)
    for item in admins or []:
        add(item)
    for item in profile_stems or []:
        add(item)
    for edge in (relations or {}).get("edges") or []:
        add(edge.get("a"))
        add(edge.get("b"))
    for group in ((relations or {}).get("groups") or {}).values():
        for edge in (group or {}).get("edges") or []:
            add(edge.get("a"))
            add(edge.get("b"))
    for card in cards or []:
        for subject in card.get("subjects") or []:
            add(subject)
    for umo in (scopes or {}):
        add(str(umo).rsplit(":", 1)[-1])
    return ids
