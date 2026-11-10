"""合并转发解析的纯逻辑：把 OneBot get_forward_msg 的节点压成文本。

不依赖 AstrBot，可单独测试。只处理结构，不负责网络请求。
"""

from __future__ import annotations

from typing import Any

MAX_CHARS = 6000


def _sender_name(node: dict) -> str:
    sender = node.get("sender") or {}
    if isinstance(sender, dict):
        return str(sender.get("card") or sender.get("nickname") or sender.get("name") or "").strip()
    return ""


def segment_text(segment: Any) -> str:
    """把 OneBot 消息段转成简短文本；图片/视频只留占位符。"""
    if not isinstance(segment, dict):
        return ""
    kind = str(segment.get("type") or "").lower()
    data = segment.get("data") or {}
    if not isinstance(data, dict):
        data = {}
    if kind == "text":
        return str(data.get("text") or "")
    if kind in ("image", "mface"):
        return "[图片]"
    if kind == "face":
        return f"[表情:{data.get('id')}]"
    if kind == "video":
        return "[视频]"
    if kind == "record":
        return "[语音]"
    if kind in ("forward", "node"):
        return "[嵌套转发]"
    if kind == "at":
        return f"@{data.get('name') or data.get('qq') or ''}"
    if kind == "json":
        return "[卡片]"
    return ""


def flatten_nodes(
    messages: list[dict],
    limit_chars: int = MAX_CHARS,
    include_sender: bool = True,
) -> str:
    """把 get_forward_msg 返回的 messages 压成「昵称：内容」多行文本。"""
    lines = []
    total = 0
    for node in messages or []:
        if not isinstance(node, dict):
            continue
        parts = []
        for segment in node.get("message") or []:
            text = segment_text(segment)
            if text:
                parts.append(text)
        body = "".join(parts).strip()
        if not body:
            continue
        name = _sender_name(node) if include_sender else ""
        line = f"{name}：{body}" if name else body
        if total + len(line) > limit_chars:
            lines.append("……（转发内容太长，已截断）")
            break
        lines.append(line)
        total += len(line) + 1
    return "\n".join(lines)


def nested_forward_ids(messages: list[dict]) -> list[str]:
    """找出转发节点里嵌套的 forward id（用于多层展开）。"""
    ids = []
    for node in messages or []:
        if not isinstance(node, dict):
            continue
        for segment in node.get("message") or []:
            if not isinstance(segment, dict):
                continue
            if str(segment.get("type") or "").lower() not in ("forward", "node"):
                continue
            data = segment.get("data") or {}
            if not isinstance(data, dict):
                continue
            fid = str(data.get("id") or data.get("res_id") or data.get("forward_id") or "").strip()
            if fid and fid not in ids:
                ids.append(fid)
    return ids
