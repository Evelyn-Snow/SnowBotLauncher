"""印象笔记插件的纯逻辑：画像文件的渲染/解析、昵称史合并、注入摘要、更新门槛。

不依赖 AstrBot，可单独单测。画像文件以 QQ 号命名（<QQ号>.md），
frontmatter 记录 qq/昵称/历史昵称/更新时间/互动次数，正文是画像内容。
"""

from __future__ import annotations

import datetime as _dt
import math
import re

_NAME_DATE_RE = re.compile(r"^(.*?)（(\d{4}-\d{2}-\d{2})）$")

# 画像是她自己写的印象笔记，注入时的标记也用它（inject_profile 靠这个标记防重复注入）
SUMMARY_MARK = "[我记下的TA]"
LEGACY_TITLE_PREFIX = "用户画像："
TITLE_PREFIX = "我眼里的"


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
    impression_score: int | None = None,
    familiarity_score: int | None = None,
    familiarity_level: str = "",
    active_days: int = 0,
    first_seen: str = "",
    last_seen: str = "",
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
    if impression_score is not None:
        lines.append(f"印象评分: {max(0, min(100, int(impression_score)))}")
    if familiarity_score is not None:
        lines.append(f"熟悉度: {max(0, min(100, int(familiarity_score)))}")
    if familiarity_level:
        lines.append(f"熟悉等级: {familiarity_level}")
    if active_days:
        lines.append(f"活跃天数: {max(0, int(active_days))}")
    if first_seen:
        lines.append(f"首次互动: {first_seen}")
    if last_seen:
        lines.append(f"最近互动: {last_seen}")
    # 正文里可能带着旧 H1 标题；标题由这里统一生成，避免重复
    body_text = re.sub(
        r"^\s*#\s+.*(?:\n+|$)", "", str(body or "").strip(), count=1
    ).strip()
    lines += ["---", "", f"# {TITLE_PREFIX}{name or qq}（{qq}）", "", body_text, ""]
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
        "impression_score": None,
        "familiarity_score": None,
        "familiarity_level": "",
        "active_days": 0,
        "first_seen": "",
        "last_seen": "",
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
        elif key == "印象评分":
            try:
                result["impression_score"] = max(0, min(100, int(value)))
            except ValueError:
                pass
        elif key == "熟悉度":
            try:
                result["familiarity_score"] = max(0, min(100, int(value)))
            except ValueError:
                pass
        elif key == "熟悉等级":
            result["familiarity_level"] = value
        elif key == "活跃天数":
            try:
                result["active_days"] = max(0, int(value))
            except ValueError:
                pass
        elif key == "首次互动":
            result["first_seen"] = value
        elif key == "最近互动":
            result["last_seen"] = value
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


# ---------------- 熟悉度 ----------------

FAMILIARITY_LEVELS = (
    (88, "知己"),
    (79, "亲近"),
    (68, "好友"),
    (56, "好朋友"),
    (44, "朋友"),
    (32, "熟人"),
    (20, "认识"),
    (10, "眼熟"),
    (0, "陌生"),
)
ADMIN_FAMILIARITY_LEVEL = "管理员"

_FAMILIARITY_GUIDES = {
    "管理员": "这是管理员/主人：可以亲昵、撒娇，但别越界，也别因为身份就一味顺从。",
    "知己": "很熟的老朋友：可以主动分享自己的事、吐槽、开玩笑，语气最放松。",
    "亲近": "很亲近的人：会主动关心、开玩笑，也愿意说自己的小情绪。",
    "好友": "好友：可以接梗、吐槽、分享日常，但别过度打探私事。",
    "好朋友": "好朋友：比普通朋友更随意，能开玩笑，会关心近况。",
    "朋友": "朋友：可以随意接梗、开玩笑，聊日常；不要过度打听私事。",
    "熟人": "熟人：客气但放松，能接梗；不主动深入私事，不撒娇。",
    "认识": "认识不久：礼貌、友好，保持一点距离，不主动问私事。",
    "眼熟": "只是眼熟：客气、简短，别自来熟，也别撒娇。",
    "陌生": "陌生人：礼貌、保持距离，不主动套近乎，不透露自己的事。",
}


def _clamp_score(value, default: int = 50) -> int:
    try:
        return max(0, min(100, int(round(float(value)))))
    except (TypeError, ValueError):
        return default


def familiarity_level(score, is_admin: bool = False) -> str:
    if is_admin:
        return ADMIN_FAMILIARITY_LEVEL
    value = _clamp_score(score, 0)
    for threshold, label in FAMILIARITY_LEVELS:
        if value >= threshold:
            return label
    return "陌生"


def compute_familiarity(
    exchanges: int,
    active_days: int,
    impression: int,
    moral: int,
    days_since_last: float = 0.0,
    is_admin: bool = False,
) -> tuple[int, str]:
    """聊天频率 + 印象分 + 道德分 → 0~100 熟悉度；非管理员最高 94（知己）。"""
    if is_admin:
        return 100, ADMIN_FAMILIARITY_LEVEL
    exchanges = max(0, int(exchanges or 0))
    active_days = max(0, int(active_days or 0))
    impression = _clamp_score(impression)
    moral = _clamp_score(moral)
    frequency = min(
        100.0, 12.0 * math.log10(1 + exchanges) + active_days * 1.2
    )
    base = 0.45 * frequency + 0.30 * impression + 0.25 * moral
    confidence = min(
        1.0, 0.5 * (exchanges / 30.0) + 0.5 * (active_days / 10.0)
    )
    score = base * confidence
    days = max(0.0, float(days_since_last or 0))
    if days > 90:
        score *= 0.6
    elif days > 30:
        score *= 0.85
    score = max(0, min(94, int(round(score))))
    return score, familiarity_level(score)


def familiarity_guidance(level: str) -> str:
    return _FAMILIARITY_GUIDES.get(str(level or ""), _FAMILIARITY_GUIDES["陌生"])


_IMPRESSION_RE = re.compile(r"印象评分[:：]\s*(\d{1,3})")


def extract_impression(text: str, default: int = 50) -> int:
    match = _IMPRESSION_RE.search(str(text or ""))
    if not match:
        return _clamp_score(default)
    return _clamp_score(match.group(1), _clamp_score(default))


def strip_impression(text: str) -> str:
    return "\n".join(
        line
        for line in str(text or "").splitlines()
        if "印象评分" not in line
    ).strip()


def smooth_score(old, new, alpha: float = 0.3) -> int:
    """分数平滑，避免一次对话就让印象大起大落。"""
    old_value = _clamp_score(old)
    new_value = _clamp_score(new)
    ratio = max(0.0, min(1.0, float(alpha)))
    return _clamp_score(old_value * (1 - ratio) + new_value * ratio)


def _drop_headings(text: str) -> str:
    """去掉 markdown 标题行（注入时不需要「## 我们常聊什么」这种结构词）。"""
    return "\n".join(
        line for line in str(text or "").splitlines() if not line.lstrip().startswith("#")
    )


def profile_summary(md: str, limit: int = 400, include_moral: bool = False) -> str:
    """把画像压成注入用的一段话：去掉 frontmatter、标题与标题符号，超长截断。

    画像是第一人称写的，注入时用「我记下的TA」打头，让她读起来像自己的记忆。
    默认剔除「## 道德评价」小节（它由 moral_injection 单独注入，避免重复）。
    """
    parsed = parse_profile(md)
    body = parsed["body"]
    if not include_moral:
        idx = body.find(MORAL_SECTION_MARK)
        if idx != -1:
            body = body[:idx]
    # 标题（H1/H2）都去掉：昵称已由 head 给出，小节名对注入没有意义
    body = _drop_headings(body)
    body = re.sub(r"\n{2,}", "\n", body).replace("\n", "；").strip("； \t")
    body = body.replace("。；", "。").replace("；；", "；")
    head = f"昵称：{parsed['name'] or parsed['qq'] or '未知'}"
    summary = f"{SUMMARY_MARK} {head}；{body}" if body else f"{SUMMARY_MARK} {head}"
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


# ---------------- 主动消息时间窗与虚拟人生 ----------------

_HHMM_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


def _hhmm_minutes(raw: str) -> int | None:
    match = _HHMM_RE.match(str(raw or "").strip())
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour == 24 and minute == 0:
        return 1440
    if not (0 <= hour < 24 and 0 <= minute < 60):
        return None
    return hour * 60 + minute


def _time_ranges(spec: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for part in re.split(r"[,，\s]+", str(spec or "")):
        if "-" not in part:
            continue
        left, right = part.split("-", 1)
        start, end = _hhmm_minutes(left), _hhmm_minutes(right)
        if start is None or end is None or start == end:
            continue
        ranges.append((start, end))
    return ranges


def in_time_windows(spec: str, hhmm: str) -> bool:
    """主动消息时间窗：'12:00-13:30,18:00-22:00'；空配置视为全天。"""
    ranges = _time_ranges(spec)
    if not ranges:
        return True
    now = _hhmm_minutes(hhmm)
    if now is None:
        return False
    for start, end in ranges:
        if start < end:
            if start <= now < end:
                return True
        elif now >= start or now < end:
            return True
    return False


def pick_today_plan(
    plans_data: dict, today: str, persona_id: str = ""
) -> dict | None:
    """从虚拟人生 plans.json 里选今天的日程（同 sleep 插件的匹配规则）。"""
    plans = plans_data.get("plans") if isinstance(plans_data, dict) else None
    if not isinstance(plans, dict):
        return None
    matching = [
        value
        for key, value in plans.items()
        if isinstance(value, dict) and str(key).startswith(f"{today}::")
    ]
    if not matching:
        return None
    if persona_id:
        for plan in matching:
            if str(plan.get("persona_id", "")) == persona_id:
                return plan
    return matching[0] if len(matching) == 1 else None


def current_timeline_item(plan: dict, hhmm: str) -> dict | None:
    """从虚拟人生今日日程里取当前时段的活动。"""
    if not isinstance(plan, dict):
        return None
    now = _hhmm_minutes(hhmm)
    if now is None:
        return None
    timeline = plan.get("timeline")
    if not isinstance(timeline, list):
        return None
    for item in timeline:
        if not isinstance(item, dict):
            continue
        start = _hhmm_minutes(str(item.get("start") or ""))
        end = _hhmm_minutes(str(item.get("end") or ""))
        if start is None or end is None or start == end:
            continue
        inside = (
            start <= now < end
            if start < end
            else (now >= start or now < end)
        )
        if inside:
            return item
    return None


def activity_allows_proactive(item: dict | None) -> bool:
    """虚拟人生活动是否适合主动聊天：睡觉/忙/在路上/低可打扰度都不发。"""
    if not isinstance(item, dict):
        return True  # 没日程数据时退回时间窗判断
    state = str(item.get("state") or "").strip().lower()
    availability = str(item.get("availability") or "").strip().lower()
    if state in ("sleep", "busy", "transit"):
        return False
    if availability in ("blocked", "low"):
        return False
    activity = str(item.get("activity") or "")
    if any(
        word in activity
        for word in ("睡觉", "睡眠", "上课", "开会", "面试", "聊天", "约会", "打电话", "通话")
    ):
        return False
    return state in ("available", "social") or any(
        word in activity for word in ("午休", "休息", "下班", "空闲", "午餐", "晚饭", "晚餐", "吃饭")
    )


def activity_line(item: dict | None) -> str:
    if not isinstance(item, dict):
        return ""
    activity = str(item.get("activity") or "").strip()
    location = str(item.get("location") or "").strip()
    if not activity:
        return ""
    return f"{activity}（{location}）" if location else activity


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


# ---------------- 画像正文的生成提示 ----------------
# 画像是「她自己记下的印象」，不是系统档案：用第一人称、用她平时说话的口吻。
# 旧档案可能是第三人称，提示里明确要求一并改写。

PROFILE_SYSTEM_PROMPT = (
    "你就是对话记录里的「我」：一个有自己性格和情绪的人，正在写只给自己看的印象笔记。"
    "用第一人称、用你平时说话的口吻写，不要写成客观档案；只依据给定对话，不编造、"
    "不评价外貌，不写没有依据的敏感信息。只输出笔记正文本身。"
)

PROFILE_VOICE_RULES = (
    "请更新你私下记的这份印象笔记：\n"
    "- 正文最前面单独写一行「印象评分：NN」（0-100，50 是中性；根据 TA 对你的态度、"
    "互动质量、是否真诚来评，别大起大落），空一行再写正文；\n"
    "- 用第一人称写，就像你自己在日记里记下这个人：提到对方用 TA 的昵称或「他/她」，提到自己用「我」；\n"
    "- 用你平时聊天的语气和性格写，可以带情绪、有自己的判断和态度；\n"
    "- 不要写成客观档案，不要用「该用户」「对方」「助手」这类第三人称，也不要写「用户画像」；\n"
    "- 旧档案如果是第三人称口吻，这次一并改写成第一人称；\n"
    "- 保留仍有价值的旧结论，用新对话修正或补充；只写有依据的内容，没发生过的不要编造；\n"
    "- 用 ## 小节组织（我眼里的TA、TA说话的样子、我们常聊什么、跟TA相处要注意什么、最近的事），"
    "中文、口语、简洁，总共不超过 500 字。\n"
    "不要输出 frontmatter、不要代码块、不要任何解释。"
)


def _moral_rules(today: str) -> str:
    return (
        "末尾必须有一个「## 道德评价」小节，**只写本轮新增的记录**（不要重复旧记录，"
        "没有新证据就只写一行「本轮无新增记录」）。每条记录一行，格式：\n"
        f"- [±N] 用你自己的话写一句判断：『引用对方原话』（{today}）\n"
        "评分规则：恶劣引导、教唆违规、骚扰暗示、人格侮辱等行为每条 -10~-25；"
        "对方真诚道歉或改正 +5~+15；观点不同、玩笑、普通粗口不记。"
        "每条都必须引用原话作证据；不要自己计算总分，总分由系统维护。"
    )


def build_profile_prompt(old_md: str, recent: str, today: str) -> str:
    """拼出「用她自己的口吻重写印象笔记」的用户提示。"""
    old = str(old_md or "").strip()
    existing = (
        f"你之前记下的印象笔记：\n{old[:2500]}"
        if old
        else "你还没记过这个人，这是第一次。"
    )
    return (
        f"{existing}\n\n"
        f"最近和这个人的对话（按时间正序，里面的「我」就是你本人）：\n{recent}\n\n"
        f"{PROFILE_VOICE_RULES}\n\n{_moral_rules(today)}"
    )


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
    head = f"[我记下的TA·不太对劲] 这个人在我心里的评分很低（等级：{level}）。"
    parts = [head]
    if evidence:
        parts.append(evidence)
    parts.append(f"（交流指引：{tone}若TA真诚道歉并改正，可逐步恢复态度。）")
    return "\n".join(parts)
