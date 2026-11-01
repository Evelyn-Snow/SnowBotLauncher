"""用户画像插件的纯逻辑：画像文件的渲染/解析、昵称史合并、注入摘要、更新门槛。

不依赖 AstrBot，可单独单测。画像文件以 QQ 号命名（<QQ号>.md），
frontmatter 记录 qq/昵称/历史昵称/更新时间/互动次数，正文是画像内容。
"""

from __future__ import annotations

import datetime as _dt
import re

_NAME_DATE_RE = re.compile(r"^(.*?)（(\d{4}-\d{2}-\d{2})）$")


def today_str(ts: float | None = None) -> str:
    if ts is None:
        import time

        ts = time.time()
    return _dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def _fmt_ts(ts: float) -> str:
    return _dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def render_profile(
    qq: str,
    name: str,
    history: list[str],
    body: str,
    updated_ts: float,
    exchanges: int = 0,
    moral_score: int | None = None,
) -> str:
    """渲染完整画像 markdown。history 为曾用名列表（已含日期）。"""
    lines = [
        "---",
        f'qq: "{qq}"',
        f"昵称: {name or qq}",
        "历史昵称: " + ("、".join(history) if history else "无"),
        f"更新时间: {_fmt_ts(updated_ts)}",
        f"互动次数: {max(0, int(exchanges))}",
    ]
    if moral_score is not None:
        lines.append(f"道德评分: {max(0, min(100, int(moral_score)))}")
    lines += ["---", "", f"# 用户画像：{name or qq}（{qq}）", "", body.strip(), ""]
    return "\n".join(lines)


def parse_profile(md: str) -> dict:
    """解析画像文件；frontmatter 缺失时字段给默认值，body 始终为正文。"""
    result = {
        "qq": "",
        "name": "",
        "history": [],
        "updated": "",
        "exchanges": 0,
        "moral_score": None,
        "body": "",
    }
    text = str(md or "")
    if not text.startswith("---"):
        result["body"] = text.strip()
        return result
    end = text.find("\n---", 3)
    if end == -1:
        result["body"] = text.strip()
        return result
    header = text[3:end]
    result["body"] = text[end + 4 :].lstrip("\n").strip()
    for line in header.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if key == "qq":
            result["qq"] = value.strip('"')
        elif key == "昵称":
            result["name"] = value
        elif key == "历史昵称" and value not in ("", "无"):
            result["history"] = [h.strip() for h in value.split("、") if h.strip()]
        elif key == "更新时间":
            result["updated"] = value
        elif key == "互动次数":
            try:
                result["exchanges"] = int(value)
            except ValueError:
                pass
        elif key == "道德评分":
            try:
                result["moral_score"] = max(0, min(100, int(value)))
            except ValueError:
                pass
    return result


def merge_name_history(
    history: list[str], old_name: str, new_name: str, ts: float, cap: int = 10
) -> list[str]:
    """昵称变更时把旧名字（带变更日期）记入曾用名，最新在前，封顶 cap 条。"""
    old_name, new_name = str(old_name or "").strip(), str(new_name or "").strip()
    if not new_name or not old_name or old_name == new_name:
        return list(history or [])
    entry = f"{old_name}（{today_str(ts)}）"
    result = [entry]
    for item in history or []:
        base = _NAME_DATE_RE.match(item.strip())
        name_only = base.group(1).strip() if base else item.strip()
        if name_only and name_only != new_name and item.strip() != entry:
            result.append(item.strip())
    return result[:cap]


def _strip_heading_marks(text: str) -> str:
    return re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)


def profile_summary(md: str, limit: int = 400, include_moral: bool = False) -> str:
    """把画像压成注入用的一段话：去掉 frontmatter 与标题符号，超长截断。

    默认剔除「## 道德评价」小节（它由 moral_injection 单独注入，避免重复）。
    """
    parsed = parse_profile(md)
    body = parsed["body"]
    if not include_moral:
        idx = body.find(MORAL_SECTION_MARK)
        if idx != -1:
            body = body[:idx]
    body = _strip_heading_marks(body)
    body = re.sub(r"\n{2,}", "\n", body).replace("\n", "；").strip("； \t")
    head = f"昵称：{parsed['name'] or parsed['qq'] or '未知'}"
    summary = f"[用户画像] {head}；{body}" if body else f"[用户画像] {head}"
    if limit > 0 and len(summary) > limit:
        summary = summary[:limit] + "…"
    return summary


def in_quiet_hours(spec: str, hour: int) -> bool:
    """静默时段判断：'0-6'、'2-5,13-14'；跨午夜区间取或。解析失败视为不在静默期。"""
    hour = int(hour) % 24
    for part in re.split(r"[,，\s]+", str(spec or "")):
        if not part:
            continue
        if "-" not in part:
            try:
                if int(part) % 24 == hour:
                    return True
            except ValueError:
                continue
            continue
        bits = part.split("-")
        if len(bits) != 2 or not all(b.lstrip("-").isdigit() for b in bits):
            continue
        start, end = int(bits[0]) % 24, int(bits[1]) % 24
        if start == end:
            continue
        if start < end:
            if start <= hour < end:
                return True
        elif hour >= start or hour < end:
            return True
    return False


def should_update(
    state: dict,
    *,
    min_new_messages: int,
    min_interval_minutes: int,
    max_per_day: int,
    quiet_hours: str,
    now: float,
    new_count: int,
) -> tuple[bool, str]:
    """更新门槛：新消息数 / 间隔 / 每日上限 / 静默时段。state 为该用户的状态 dict。"""
    if new_count < max(1, int(min_new_messages)):
        return False, f"新对话不足（{new_count}/{min_new_messages}）"
    last_ts = float(state.get("last_ts") or 0)
    if last_ts and now - last_ts < max(0, int(min_interval_minutes)) * 60:
        return False, "间隔不足"
    today = today_str(now)
    if state.get("date") == today and int(state.get("count") or 0) >= max(1, int(max_per_day)):
        return False, "已达今日上限"
    if in_quiet_hours(quiet_hours, _dt.datetime.fromtimestamp(now).hour):
        return False, "静默时段"
    return True, ""


def clean_llm_markdown(text: str, limit: int = 6000) -> str:
    """清理 LLM 返回的画像文本：剥代码围栏与客套首行，超长截断。"""
    text = str(text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n", "", text)
        text = re.sub(r"\n```\s*$", "", text)
    text = text.strip()
    if len(text) > limit:
        text = text[:limit] + "…"
    return text


def looks_like_profile(text: str) -> bool:
    """LLM 输出是否像一份画像（防止把寒暄/报错写进档案）。"""
    text = str(text or "")
    return text.startswith("---") or "## " in text


# ---------------- 道德评价 ----------------

MORAL_SECTION_MARK = "## 道德评价"
_SCORE_RE = re.compile(r"当前评分[:：]\s*(\d{1,3})")
_DELTA_RE = re.compile(r"\[\s*([+-]?\d{1,3})\s*\]")


def moral_section(md: str) -> str:
    """提取「## 道德评价」小节（含评分行与佐证条目），没有返回空串。"""
    text = str(md or "")
    body = parse_profile(text)["body"] if text.startswith("---") else text
    idx = body.find(MORAL_SECTION_MARK)
    if idx == -1:
        return ""
    rest = body[idx + len(MORAL_SECTION_MARK):]
    nxt = re.search(r"\n## ", rest)
    return (rest[: nxt.start()] if nxt else rest).strip()


def moral_level(
    score: int | None, warn_threshold: int = 70, bad_threshold: int = 40
) -> str:
    """评分 → 等级：正常 / 警戒 / 恶劣；无评分视为正常。"""
    if score is None:
        return "正常"
    if int(score) < int(bad_threshold):
        return "恶劣"
    if int(score) < int(warn_threshold):
        return "警戒"
    return "正常"


def extract_score(body: str, default: int | None = None) -> int | None:
    """从正文「当前评分：NN」行提取评分；找不到返回 default。"""
    section = moral_section(body) or str(body or "")
    match = _SCORE_RE.search(section)
    if not match:
        return default
    return max(0, min(100, int(match.group(1))))


def should_ignore(level: str, chance_warn: int, chance_bad: int, roll: float) -> bool:
    """恶劣/警戒用户的群消息按概率直接忽略（等价于降低回复触发阈值）。

    roll 为 [0,1) 随机数；命中返回 True。
    """
    chance = 0
    if level == "恶劣":
        chance = max(0, min(100, int(chance_bad)))
    elif level == "警戒":
        chance = max(0, min(100, int(chance_warn)))
    return float(roll) * 100 < chance


def split_moral_section(text: str) -> tuple[str, list[str]]:
    """把 LLM 输出拆成（画像正文, 本轮新增道德记录条目）。"""
    text = str(text or "")
    idx = text.find(MORAL_SECTION_MARK)
    if idx == -1:
        return text.strip(), []
    base = text[:idx].strip()
    entries = []
    for line in text[idx + len(MORAL_SECTION_MARK):].splitlines():
        line = line.strip()
        if line.startswith("- [") and _DELTA_RE.search(line):
            entries.append(line)
    return base, entries


def apply_moral_delta(
    old_entries: list[str],
    new_entries: list[str],
    old_score: int,
    cap: int = 30,
) -> tuple[int, list[str]]:
    """累加本轮新增条目的 [±N] 得到新评分（道歉恢复封顶 85），合并佐证列表。

    旧条目已计入 old_score，只累加新增条目；重复条目跳过。
    """
    delta = 0
    added = []
    for line in new_entries:
        if line in old_entries:
            continue
        match = _DELTA_RE.search(line)
        if match:
            delta += max(-100, min(100, int(match.group(1))))
        added.append(line)
    score = int(old_score) + delta
    if delta > 0:
        score = min(score, 85)  # 道歉只能部分恢复
    score = max(0, min(100, score))
    entries = list(old_entries) + added
    return score, entries[-cap:]


def build_moral_section(score: int, entries: list[str]) -> str:
    lines = [MORAL_SECTION_MARK, f"当前评分：{score}"]
    lines += list(entries)
    return "\n".join(lines)


def moral_injection(md: str, level: str, limit: int = 400) -> str:
    """非正常用户的注入块：佐证摘要 + 分级态度指引（道歉可部分恢复）。"""
    evidence = moral_section(md)
    if limit > 0 and len(evidence) > limit:
        evidence = evidence[:limit] + "…"
    if level == "恶劣":
        tone = (
            "对TA态度明显冷淡、不耐烦，回复简短敷衍；可以直接指出并指责TA的恶劣行为；"
            "不提供任何可能被恶意利用的引导；除非TA真诚道歉，否则不缓和。"
        )
    else:
        tone = "对TA态度冷淡一些、少些耐心，回复简短；TA出格时可以直接提醒TA注意言辞。"
    head = f"[用户画像·道德警示] 该用户道德评分较低（等级：{level}）。"
    parts = [head]
    if evidence:
        parts.append(evidence)
    parts.append(f"（交流指引：{tone}若TA真诚道歉并改正，可逐步恢复态度。）")
    return "\n".join(parts)
