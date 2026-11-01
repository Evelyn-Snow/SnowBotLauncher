"""QQ 分享卡片（Json 组件）转纯文本的提取逻辑（不依赖 AstrBot，可单独测试）。

QQ 里分享 B站/网页链接时，消息是 Json 卡片（无纯文本），模型完全看不到内容。
这里递归提取卡片里的标题、描述和链接，优先 bilibili/b23 短链，
拼成一段可追加到消息链的纯文本，让下游（BiliRead、网页分析、读空气）都能看见。
"""

from __future__ import annotations

import json
import re

_URL_RE = re.compile(r"https?://[^\s\"'<>\\]+")
_KEY_TITLE = ("title", "标题")
_KEY_DESC = ("desc", "description", "desc_high", "摘要")
_KEY_URL = ("url", "qqdocurl", "jump_url", "share_url")
_BILI_HINTS = ("b23.tv", "bilibili.com", "bilibili")

# 卡片文本里可能伪造的"系统指令"样式（外部可控内容不能伪装成系统消息）
_FAKE_DIRECTIVE_RE = re.compile(
    r"(?:\[\s*(?:系统|system|指令|instruction|admin|管理员)[^\]]{0,20}\]"
    r"|<\s*/?\s*(?:system|instruction)[^>]*>"
    r"|^\s*(?:system|assistant|user)\s*[:：])",
    re.IGNORECASE | re.MULTILINE,
)
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_card_text(text: str, limit: int = 300) -> str:
    """清理卡片文本：折叠换行/控制字符、去掉伪造的系统指令样式、截断。

    QQ 卡片的标题/描述是对方可控内容，不清理就能伪造多行指令混进用户消息。
    """
    value = str(text or "")
    if not value:
        return ""
    value = _CTRL_RE.sub(" ", value)
    value = re.sub(r"[\r\n\t]+", " ", value)
    value = _FAKE_DIRECTIVE_RE.sub("[已过滤]", value)
    value = re.sub(r"[ \u3000]{2,}", " ", value).strip()
    if limit > 0 and len(value) > limit:
        value = value[:limit] + "…"
    return value


def _walk_strings(obj):
    """递归产出 (key, value) 对（value 为非容器值）。"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk_key_value(k, v)
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk_key_value("", item)


def _walk_key_value(key, value):
    if isinstance(value, dict):
        yield from _walk_strings(value)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_key_value(key, item)
    else:
        yield str(key or ""), value


def _first_url(text: str, prefer_bili: bool) -> str:
    urls = _URL_RE.findall(text or "")
    if prefer_bili:
        for u in urls:
            if any(h in u.lower() for h in _BILI_HINTS):
                return u
    return urls[0] if urls else ""


def extract_share_text(data: str | dict) -> str | None:
    """从 QQ 分享卡片提取「标题；描述；链接」纯文本。无有效内容返回 None。"""
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            return None
    if not isinstance(data, (dict, list)):
        return None

    title = desc = ""
    url = ""
    bili_url = ""
    for key, value in _walk_strings(data):
        v = str(value or "").strip()
        if not v or len(v) > 500:
            continue
        k = key.lower()
        if not title and any(t == k for t in _KEY_TITLE):
            title = v
        elif not desc and any(t == k for t in _KEY_DESC) and v != title:
            desc = v
        u = _first_url(v, prefer_bili=False)
        if u and not url:
            url = u
        if any(h in u.lower() or h in v.lower() for h in _BILI_HINTS):
            bu = _first_url(v, prefer_bili=True)
            if bu and not bili_url:
                bili_url = bu
    url = bili_url or url

    parts = []
    if title:
        parts.append(f"标题：{sanitize_card_text(title)}")
    if desc and desc != title:
        parts.append(f"内容：{sanitize_card_text(desc, limit=200)}")
    if url:
        parts.append(f"链接：{sanitize_card_text(url, limit=500)}")
    if not parts:
        return None
    return "[分享卡片] " + "；".join(parts)


def looks_like_bilibili_share(data: str | dict) -> bool:
    text = json.dumps(data, ensure_ascii=False) if not isinstance(data, str) else str(data)
    return any(h in text.lower() for h in _BILI_HINTS)


def merge_share_text(existing: str, share: str) -> str:
    """把分享卡片文本合并进已有纯文本，避免重复空行。"""
    base = str(existing or "").strip()
    extra = str(share or "").strip()
    if not base:
        return extra
    if not extra:
        return base
    return base + "\n" + extra
