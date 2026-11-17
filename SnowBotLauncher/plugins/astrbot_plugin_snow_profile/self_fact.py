"""「我的近况」纯逻辑：从她的回复里抽取关于自己的事实，并生成注入文本。

共享记忆卡片是按会话摘要生成的、受分享评级限制；这里专门记「我自己说过的事」
（吃了什么、去了哪、在做什么），不依赖卡片是否生成、也不受听众关系限制。
只抽取第一人称分句，涉及对方/第三方或敏感内容的分句不记。
"""

from __future__ import annotations

import re
import time

FACT_MARK = "[我的近况]"

_FACT_WORDS = (
    "吃", "喝", "去", "在", "买", "做", "写", "看", "听", "睡", "起",
    "洗", "跑", "学", "准备", "打算", "正在", "刚刚", "刚", "今天", "明天",
    "晚上", "中午", "早上", "下午", "宿舍", "食堂", "图书馆", "回家",
)
_SENSITIVE = (
    "密码", "验证码", "身份证", "银行卡", "工资", "收入", "病历", "年龄",
    "住址", "电话", "手机号", "QQ号", "qq号", "账号", "地址", "定位",
)
_OTHER = ("你", "对方", "他", "她", "他们", "她们")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip("，。！？；：,.;: ")


def extract_self_facts(text: str, limit: int = 6) -> list[str]:
    """从回复里抽取关于「我」的分句；不含对方/第三方，也不含敏感信息。"""
    out = []
    for sentence in re.split(r"[。！？!?\n]+", str(text or "")):
        for clause in re.split(r"[，,；;]+", sentence):
            value = _clean(clause)
            if not value or len(value) < 5 or len(value) > 100:
                continue
            if "我" not in value or "？" in value or "?" in value:
                continue
            if any(word in value for word in _OTHER):
                continue
            if any(word in value for word in _SENSITIVE):
                continue
            if not any(word in value for word in _FACT_WORDS):
                continue
            if value not in out:
                out.append(value)
            if len(out) >= max(1, int(limit)):
                return out
    return out


def merge_self_facts(
    facts: list[dict],
    text: str,
    now: float | None = None,
    scope: str = "",
    cap: int = 120,
) -> int:
    """把一条事实合并进列表；完全相同的内容只更新时间。"""
    now = float(now if now is not None else time.time())
    value = _clean(text)
    if not value:
        return 0
    for item in facts or []:
        if isinstance(item, dict) and _clean(item.get("text")) == value:
            item["ts"] = now
            if scope:
                item["scope"] = scope
            return 1
    facts.append({"text": value, "ts": now, "scope": str(scope or "")})
    if cap > 0 and len(facts) > cap:
        facts.sort(key=lambda item: float(item.get("ts") or 0))
        del facts[: len(facts) - cap]
    return 1


def format_self_facts(
    facts: list[dict],
    now: float | None = None,
    limit: int = 3,
    ttl_hours: int = 72,
) -> str:
    """取最近几条未过期的事实，生成注入块。"""
    now = float(now if now is not None else time.time())
    ttl = max(1, int(ttl_hours or 72)) * 3600
    rows = []
    for item in facts or []:
        if not isinstance(item, dict):
            continue
        try:
            ts = float(item.get("ts") or 0)
        except (TypeError, ValueError):
            continue
        if ts <= 0 or now - ts > ttl:
            continue
        text = _clean(item.get("text"))
        if text:
            rows.append((ts, text))
    rows.sort(reverse=True)
    if not rows:
        return ""
    lines = []
    for ts, text in rows[: max(1, int(limit))]:
        stamp = time.strftime("%m-%d %H:%M", time.localtime(ts))
        lines.append(f"- {stamp}：{text}")
    return (
        FACT_MARK
        + " 这些是我自己最近说过、真实做过的事，事实以这里为准；"
        "同一件事不要改口，时间最新的优先，不确定就用模糊说法。\n"
        + "\n".join(lines)
    )
