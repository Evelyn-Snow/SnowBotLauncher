"""小雪全局记忆层的纯逻辑：事实校验、隐私过滤、检索打分与提示词渲染。

设计目标（Phase 1+2 的骨架）：

- 事件（events）是唯一事实源，只追加不改写；
- 事实（facts）是 subject-predicate-object 结构，带双时间轴、置信度、
  隐私级别和证据事件 ID；
- 洞察（insights）是从多条事实归纳出的稳定认识，必须引用事实 ID；
- 检索按“当前听众”过滤，全局学习不等于全局复述。

这里不 import AstrBot，方便单测。
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
import unicodedata
from datetime import datetime

# ---------------- 词表 ----------------

FACT_TYPES = {
    "identity",
    "preference",
    "relationship",
    "possession",
    "plan",
    "commitment",
    "boundary",
    "state",
    "skill",
    "event",
    "other",
}

PREDICATES = {
    "name",
    "likes",
    "dislikes",
    "is_a",
    "works_as",
    "studies",
    "lives_in",
    "has_pet",
    "owns",
    "plans",
    "promised",
    "is_related_to",
    "fears",
    "comforted_by",
    "prefers_reply_style",
    "knows_about",
    "read",
    "learned_from",
    "traveled_to",
    "ate",
    "did",
    "felt",
    "wants",
    "needs",
    "scheduled",
    "deadline",
    "status",
    "age",
    "birthday",
    "other",
}

# 这些谓词在同一主体上通常只有一个当前值，出现新值时应让旧值失效。
FUNCTIONAL_PREDICATES = {
    "name",
    "works_as",
    "lives_in",
    "status",
    "age",
    "birthday",
}

PREDICATE_LABELS = {
    "name": "叫",
    "likes": "喜欢",
    "dislikes": "不喜欢",
    "is_a": "是",
    "works_as": "在做",
    "studies": "在读",
    "lives_in": "住在",
    "has_pet": "养的宠物是",
    "owns": "拥有",
    "plans": "计划",
    "promised": "答应过",
    "is_related_to": "和…有关系",
    "fears": "害怕",
    "comforted_by": "难过时会找",
    "prefers_reply_style": "更喜欢被这样对待",
    "knows_about": "知道",
    "read": "读过",
    "learned_from": "从…学到",
    "traveled_to": "去了",
    "ate": "吃了",
    "did": "做了",
    "felt": "感觉",
    "wants": "想要",
    "needs": "需要",
    "scheduled": "安排了",
    "deadline": "截止",
    "status": "状态是",
    "age": "年龄是",
    "birthday": "生日是",
    "other": "",
}

PREDICATE_SYNONYMS = {
    "喜欢": "likes",
    "爱": "likes",
    "最爱": "likes",
    "不喜欢": "dislikes",
    "讨厌": "dislikes",
    "住在": "lives_in",
    "家住": "lives_in",
    "在…工作": "works_as",
    "工作": "works_as",
    "上班": "works_as",
    "职业": "works_as",
    "上学": "studies",
    "读书": "studies",
    "专业": "studies",
    "养了": "has_pet",
    "宠物": "has_pet",
    "有": "owns",
    "拥有": "owns",
    "打算": "plans",
    "计划": "plans",
    "准备": "plans",
    "答应": "promised",
    "承诺": "promised",
    "朋友": "is_related_to",
    "同事": "is_related_to",
    "同学": "is_related_to",
    "家人": "is_related_to",
    "害怕": "fears",
    "怕": "fears",
    "难过时": "comforted_by",
    "生日": "birthday",
    "年龄": "age",
    "岁": "age",
    "读过": "read",
    "看完": "read",
    "学到": "learned_from",
    "出差": "traveled_to",
    "去了": "traveled_to",
    "到过": "traveled_to",
    "吃了": "ate",
    "喝过": "ate",
    "想要": "wants",
    "希望": "wants",
    "需要": "needs",
    "安排": "scheduled",
    "截止": "deadline",
}

NEGATIVE_LABELS = {
    "likes": "不喜欢",
    "knows_about": "不了解",
    "read": "没读过",
    "traveled_to": "没去过",
    "has_pet": "没养",
    "owns": "没有",
    "studies": "没在读",
    "works_as": "不在做",
}


def render_fact_body(fact: dict) -> str:
    subject = str(fact.get("subject") or "").strip()
    obj = str(fact.get("object") or "").strip()
    predicate = str(fact.get("predicate") or "")
    if predicate == "is_related_to":
        return f"{subject}和{obj}有关系"
    label = PREDICATE_LABELS.get(predicate, "")
    if int(fact.get("polarity") or 1) < 0 and predicate not in ("dislikes", "fears"):
        label = NEGATIVE_LABELS.get(predicate, "不" + label)
    return f"{subject}{label}{obj}".strip()


PRIVACY_LABELS = {
    0: "绝密",
    1: "仅主人",
    2: "仅当事人",
    3: "同会话",
    4: "公开",
}

_SENTENCE_RE = re.compile(r"[。！？!?~…\n]+")
_PUNCT_RE = re.compile(r"[\s，。！？、,.!?~～…:：;；\"'“”‘’（）()\[\]【】<>《》\-]")
_DATE_RE = re.compile(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})")
_SENSITIVE_SELF = ("年龄", "岁", "住址", "地址", "密码", "身份证", "手机号", "学校", "宿舍", "电话")
_NEGATION_RE = re.compile(r"没看过|没读过|没去过|不知道|不了解|不喜欢|不爱|没养|没有")
_POSITIVE_CLAIM_PREDICATES = {
    "knows_about",
    "likes",
    "read",
    "traveled_to",
    "has_pet",
    "owns",
    "studies",
    "works_as",
}


# ---------------- 文本与时间 ----------------


def normalize_text(text: str) -> str:
    """去空白/标点、全半角统一，用于证据匹配和实体键。"""
    value = unicodedata.normalize("NFKC", str(text or ""))
    return _PUNCT_RE.sub("", value).casefold()


def subject_key(text: str, aliases: dict | None = None) -> str:
    key = normalize_text(text)
    if aliases:
        for alias, canonical in aliases.items():
            alias_key = normalize_text(alias)
            if alias_key and alias_key == key:
                return normalize_text(canonical)
    return key


def object_key(text: str) -> str:
    return normalize_text(text)


def sha1_text(text: str) -> str:
    return hashlib.sha1(str(text or "").encode("utf-8")).hexdigest()


def parse_date(value, default_ts: float | None = None) -> float:
    """把 ISO 日期/时间戳解析成 Unix 时间；失败回退 default_ts。"""
    fallback = float(default_ts if default_ts is not None else time.time())
    if value is None or value == "":
        return fallback
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        stamp = float(value)
        return stamp if stamp > 0 else fallback
    text = str(value).strip()
    if not text:
        return fallback
    try:
        return float(text)
    except ValueError:
        pass
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d",
    ):
        try:
            return datetime.strptime(text[: len(fmt) + 2], fmt).timestamp()
        except ValueError:
            continue
    match = _DATE_RE.search(text)
    if match:
        try:
            year, month, day = (int(part) for part in match.groups())
            return datetime(year, month, day).timestamp()
        except ValueError:
            return fallback
    return fallback


def format_date(ts: float | None) -> str:
    try:
        return time.strftime("%Y-%m-%d", time.localtime(float(ts or 0)))
    except Exception:
        return ""


def format_datetime(ts: float | None) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(float(ts or 0)))
    except Exception:
        return ""


# ---------------- 事实校验 ----------------


def canonical_predicate(value: str) -> str:
    raw = str(value or "").strip()
    if raw in PREDICATES:
        return raw
    lowered = raw.casefold()
    if lowered in PREDICATES:
        return lowered
    for word, predicate in PREDICATE_SYNONYMS.items():
        if word and word in raw:
            return predicate
    return "other"


def _clamp(value, low: float, high: float, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(low, min(high, number))


def _default_importance(fact_type: str) -> float:
    return {
        "identity": 0.8,
        "boundary": 0.85,
        "commitment": 0.8,
        "relationship": 0.7,
        "preference": 0.6,
        "possession": 0.55,
        "plan": 0.5,
        "skill": 0.55,
        "state": 0.45,
        "event": 0.45,
        "other": 0.4,
    }.get(fact_type, 0.45)


def object_is_concise(obj: str) -> bool:
    """object 应该是简短名词/短语，不要把整句、日期、人称塞进来。"""
    text = str(obj or "").strip()
    if not text or len(text) > 40:
        return False
    if any(ch in text for ch in "，。！？；" + chr(10)):
        return False
    if re.match(r"^\d{4}[-/年]", text):
        return False
    if any(word in text for word in ("我", "你", "您")):
        return False
    return True


def object_supported(obj: str, evidence: str) -> bool:
    """对象至少要在证据里有部分字面依据，避免“证据是 A、结论是 B”。"""
    obj_key = normalize_text(obj)
    ev_key = normalize_text(evidence)
    if not obj_key:
        return False
    if obj_key in ev_key:
        return True
    obj_bg = token_bigrams(obj)
    if not obj_bg:
        return True
    ev_bg = token_bigrams(evidence)
    if not ev_bg:
        return False
    return len(obj_bg & ev_bg) / len(obj_bg) >= 0.35


def validate_fact(
    raw: dict,
    *,
    events_text: str,
    default_ts: float,
    max_privacy: int = 4,
    aliases: dict | None = None,
    extractor_version: str = "v1",
) -> dict | None:
    """校验模型抽出的一条事实；证据对不上就丢弃（宁缺毋滥）。"""
    if not isinstance(raw, dict):
        return None
    subject = str(raw.get("subject") or "").strip()[:60]
    predicate = canonical_predicate(str(raw.get("predicate") or ""))
    obj = str(raw.get("object") or "").strip()[:120]
    evidence = str(raw.get("evidence") or "").strip()[:300]
    if not subject or not obj or not evidence:
        return None
    if not normalize_text(evidence) or normalize_text(evidence) not in normalize_text(events_text):
        return None
    if evidence.rstrip().endswith(("？", "?")):
        # 问句本身不是事实断言；答案应该在另一条证据里。
        return None
    if predicate in _POSITIVE_CLAIM_PREDICATES and _NEGATION_RE.search(evidence):
        # “没看过/不知道/没去过”不要写成肯定事实。
        return None
    if not object_is_concise(obj):
        return None
    if not object_supported(obj, evidence):
        return None
    fact_type = str(raw.get("fact_type") or "other").strip().lower()
    if fact_type not in FACT_TYPES:
        fact_type = "other"
    polarity = 1 if str(raw.get("polarity") or "positive").lower() not in ("negative", "-1", "0", "false") else -1
    confidence = _clamp(raw.get("confidence"), 0.05, 1.0, 0.7)
    importance = _clamp(
        raw.get("importance"), 0.05, 1.0, _default_importance(fact_type)
    )
    privacy = int(_clamp(raw.get("privacy"), 0, 4, 2))
    privacy = min(privacy, int(max_privacy))
    key = subject_key(subject, aliases)
    # 她自己不是“AI 助手/机器人/模型”，旧对话里如果有这种自我介绍，
    # 不要当成事实学进来（会和人格设定打架）。
    if key == "小雪" and predicate == "is_a":
        if any(
            word in obj.casefold()
            for word in ("ai", "助手", "机器人", "程序", "模型", "人工智能", "智能体")
        ):
            return None
    # 别人不能靠一句“我是你主人/管理员”拿到身份。
    if key != "哥哥" and predicate == "is_a":
        if any(word in obj for word in ("主人", "管理员", "哥哥", "owner")):
            return None
    # 隐私兜底：关于别人的事不因为模型写了 4 就真的公开；
    # 主人自己的事只在主人面前提；她自己的公开日常才允许跨会话。
    if key == "哥哥":
        privacy = min(privacy, 1)
    elif key == "小雪":
        if privacy >= 2 and not any(
            word in subject + obj for word in _SENSITIVE_SELF
        ):
            privacy = 4
    elif privacy >= 4:
        privacy = 2
    valid_from = parse_date(raw.get("valid_from"), default_ts)
    return {
        "subject": subject,
        "subject_key": key,
        "subject_type": str(raw.get("subject_type") or "person")[:20],
        "predicate": predicate,
        "object": obj,
        "object_key": object_key(obj),
        "object_type": str(raw.get("object_type") or "text")[:20],
        "fact_type": fact_type,
        "polarity": polarity,
        "confidence": confidence,
        "importance": importance,
        "privacy": privacy,
        "valid_from": valid_from,
        "evidence": evidence,
        "extractor_version": extractor_version,
    }


def fact_dedupe_key(fact: dict) -> str:
    return "|".join(
        [
            str(fact.get("subject_key") or ""),
            str(fact.get("predicate") or ""),
            str(fact.get("object_key") or ""),
            str(int(fact.get("polarity") or 1)),
        ]
    )


def fact_search_text(fact: dict) -> str:
    """检索文本只用事实本身，不把证据原文拼进来（否则无关事实会被证据带偏）。"""
    label = PREDICATE_LABELS.get(str(fact.get("predicate") or ""), "")
    return " ".join(
        [
            str(fact.get("subject_key") or fact.get("subject") or ""),
            label,
            str(fact.get("object_key") or fact.get("object") or ""),
        ]
    ).strip()


# ---------------- 隐私 ----------------


def audience_visible(fact: dict, audience: dict) -> bool:
    """当前听众能否看到这条事实。

    privacy:
      0 绝密（永远不注入）
      1 仅主人
      2 仅当事人（同一会话内可见）
      3 同会话/同群
      4 公开
    """
    try:
        level = int(fact.get("privacy") or 0)
    except (TypeError, ValueError):
        level = 0
    if level <= 0:
        return False
    scope = str(fact.get("scope") or "")
    current = str(audience.get("scope") or "")
    if scope and current and scope == current:
        return True
    if level >= 4:
        return True
    is_owner = bool(audience.get("is_owner"))
    if level == 1:
        # 主人的私事只在私聊里提；即使主人在群里也不搬过去。
        return is_owner and not bool(audience.get("is_group"))
    subject = str(fact.get("subject_key") or "")
    sender_key = subject_key(str(audience.get("sender_name") or ""))
    sender_id = normalize_text(str(audience.get("sender_id") or ""))
    subject_matches = bool(subject) and subject in {sender_key, sender_id}
    if level == 2:
        # 只给当事人所在的同一个会话，或主人看关于主人的事；
        # 不因为“当事人正好在群里”就把私聊内容搬进群。
        return is_owner and subject in {"哥哥", "主人", "owner"}
    if level == 3:
        return subject_matches or is_owner
    return False


# ---------------- 检索打分 ----------------


QUERY_STOPWORDS = (
    "回眸一号", "千秋雪", "Evelyn Snow", "Evelyn", "哥哥", "小雪", "主人",
    "我们", "你们", "他们", "我", "你", "他", "她", "它",
    "的", "了", "吗", "呢", "呀", "啊", "吧", "嘛", "是", "在", "有", "和",
    "什么", "怎么", "为什么", "哪", "哪个", "多少", "几点", "最近", "上次",
    "之前", "以前", "记得", "还", "说", "过", "去", "来", "这", "那",
)


def query_content(text: str) -> str:
    value = normalize_text(text)
    for word in sorted(QUERY_STOPWORDS, key=len, reverse=True):
        value = value.replace(normalize_text(word), "")
    return value


QUERY_HINTS = {
    "游戏": ("星际公民", "底特律", "通关"),
    "药": ("氨咖黄敏", "连花清瘟", "蓝苓", "胶囊"),
    "猫": ("希儿", "宠物"),
    "车": ("新车", "红色"),
    "睡": ("熬夜", "中午", "起床", "睡觉"),
    "新闻": ("新闻稿",),
}


def content_similarity(query: str, text: str) -> float:
    """去掉“哥哥/什么/吗”等高频词后再比，避免只靠主语撞上无关事实。"""
    content = query_content(query)
    if len(content) < 2:
        return text_similarity(query, text)
    bigram = text_similarity(content, text)
    q_chars = set(content)
    t_chars = set(normalize_text(text))
    char_overlap = len(q_chars & t_chars) / max(1, len(q_chars))
    score = max(bigram, char_overlap * 0.7)
    for key, hints in QUERY_HINTS.items():
        if key in query and any(hint in text for hint in hints):
            score = max(score, 0.5)
    return score


def token_bigrams(text: str) -> set[str]:
    value = normalize_text(text)
    if len(value) < 2:
        return {value} if value else set()
    return {value[i : i + 2] for i in range(len(value) - 1)}


def text_similarity(query: str, text: str) -> float:
    q = token_bigrams(query)
    t = token_bigrams(text)
    if not q or not t:
        return 0.0
    return len(q & t) / max(1, len(q))


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if not na or not nb:
        return 0.0
    return dot / (na * nb)


def score_candidate(
    candidate: dict,
    *,
    query: str,
    now: float,
    similarity: float | None = None,
) -> float:
    sim = similarity
    if sim is None:
        sim = text_similarity(query, candidate.get("search_text") or "")
    importance = _clamp(candidate.get("importance"), 0, 1, 0.4)
    confidence = _clamp(candidate.get("confidence"), 0, 1, 0.5)
    stamp = candidate.get("valid_from") or candidate.get("learned_at") or candidate.get("created_at")
    try:
        days = max(0.0, (float(now) - float(stamp or 0)) / 86400.0)
    except (TypeError, ValueError):
        days = 999.0
    recency = 1.0 / (1.0 + days / 30.0)
    return 0.55 * max(0.0, sim) + 0.2 * importance + 0.15 * confidence + 0.1 * recency


def should_recall(text: str) -> bool:
    """用户这句话是不是在问“你记得/以前/上次”这类问题。"""
    value = str(text or "")
    return bool(
        re.search(
            r"记得|还记得|上次|之前|以前|我说过|我跟你说过|你忘了|你记不记得|"
            r"我是不是|我有没有|什么时候|哪天",
            value,
        )
    )


# ---------------- 渲染 ----------------


def render_memory_block(
    facts: list[dict],
    insights: list[dict] | None = None,
    *,
    limit_chars: int = 900,
    abstain_hint: bool = False,
) -> str:
    insights = insights or []
    if not facts and not insights:
        if abstain_hint:
            return "[记忆] 这件事我没有可靠印象；不知道就直说不知道，不要编。"
        return ""
    lines = ["[记忆] 以下是我记得的事（括号里是时间和可信度；过期/不确定的不要当成现在）："]
    total = len(lines[0])
    for fact in facts:
        body = render_fact_body(fact)
        if not body:
            continue
        stamp = format_date(fact.get("valid_from") or fact.get("learned_at"))
        level = PRIVACY_LABELS.get(int(fact.get("privacy") or 0), "")
        confidence = float(fact.get("confidence") or 0)
        meta_bits = [bit for bit in (stamp, level, f"置信{confidence:.1f}") if bit]
        line = f"- {body}（{'，'.join(meta_bits)}）"
        if total + len(line) > limit_chars:
            break
        lines.append(line)
        total += len(line)
    if insights:
        header = "[我的认识] 这些是我从多次相处里归纳出来的，不是每次都对，可以随着新情况修正："
        if total + len(header) <= limit_chars:
            lines.append(header)
            total += len(header)
            for insight in insights:
                statement = str(insight.get("statement") or "").strip()
                if not statement:
                    continue
                evidence_count = len(insight.get("evidence_fact_ids") or [])
                line = f"- {statement}"
                if evidence_count:
                    line += f"（依据{evidence_count}条事实）"
                if total + len(line) > limit_chars:
                    break
                lines.append(line)
                total += len(line)
    return "\n".join(lines)


def render_profile(
    subject: str,
    facts: list[dict],
    insights: list[dict] | None = None,
    *,
    limit_chars: int = 1200,
) -> str:
    """从事实/洞察渲染一份可读画像（Phase 2 用，不直接覆盖旧画像）。"""
    insights = insights or []
    lines = [f"# 我眼里的{subject or '这个人'}"]
    total = len(lines[0])
    for insight in insights:
        statement = str(insight.get("statement") or "").strip()
        if not statement:
            continue
        line = f"- {statement}"
        if total + len(line) > limit_chars:
            break
        lines.append(line)
        total += len(line)
    if facts:
        lines.append("")
        lines.append("## 我记得的事实")
        total += len(lines[-1])
        for fact in facts:
            line = f"- {render_fact_body(fact)}"
            if total + len(line) > limit_chars:
                break
            lines.append(line)
            total += len(line)
    return "\n".join(lines)


# ---------------- 提示词 ----------------


def build_extraction_prompt(events: list[dict], max_chars: int = 7000) -> str:
    lines = []
    total = 0
    for event in events:
        stamp = format_datetime(event.get("ts"))
        source = str(event.get("source") or "chat")
        speaker = str(event.get("sender_name") or event.get("role") or "")
        text = re.sub(r"\s+", " ", str(event.get("text") or "")).strip()[:600]
        line = f"[{event.get('id')}] {stamp} [{source}] {speaker}：{text}"
        if total + len(line) > max_chars:
            break
        lines.append(line)
        total += len(line)
    body = "\n".join(lines)
    return f"""你是小雪的记忆整理器。下面是她在不同会话里真实经历/说过的话（按时间正序）。请只提取“以后还可能用到、且有原话依据”的耐久事实。

输出 JSON，格式：
{{"facts":[{{"subject":"哥哥","subject_type":"person","predicate":"likes","object":"红烧肉","object_type":"food","fact_type":"preference","polarity":"positive","confidence":0.9,"importance":0.6,"privacy":2,"valid_from":"2026-11-20","evidence":"原话片段","reason":"为什么值得记"}}],"corrections":[{{"subject":"哥哥","predicate":"lives_in","old_object":"旧值","new_object":"新值","evidence":"原话","reason":"..."}}]}}

谓词只能从这些里选：{", ".join(sorted(PREDICATES))}。
事实类型 fact_type 只能从：{", ".join(sorted(FACT_TYPES))}。

规则：
1. evidence 必须是输入里连续出现的原话/原文片段，不能改写；对不上就不要写。
2. 只写确定的事；不确定就降低 confidence 或干脆不写。寒暄、情绪宣泄、一次性闲聊、玩笑、假设不要写。
3. **优先提取对方（非 Bot）说的、可验证的事实**；你自己的话只提取真实的自我状态、承诺、偏好，忽略客套、反问、表情和玩笑。
4. **否定句不要写成肯定事实**：没看过/不知道/没去过/不喜欢不要写成 knows_about/likes/read/traveled_to；要么写 polarity=negative，要么不写。
5. **“我在做 X”是一次事件，不要写成 likes X**；用 did/event。只有明确说“我喜欢/我讨厌”才用 preference。
6. 相对时间（今天/昨天/下周）按该条消息的时间换算成 YYYY-MM-DD。
7. privacy：0=绝密（密码/证件/健康/财务），1=仅主人，2=仅当事人，3=同会话/同群，4=公开。拿不准就写 2。
8. 如果新事实和旧说法冲突，写进 corrections；没有冲突就留空数组。
9. 不要把“她说她喜欢”写成“她喜欢”，除非原话明确。
10. **object 必须是简短名词/短语（≤30 字）**，不要写整句、日期、括号说明或“我/你”等人称；日期放在 valid_from。

事件：
{body}
"""


def build_insight_prompt(
    subject: str, facts: list[dict], max_chars: int = 6000
) -> str:
    lines = []
    total = 0
    for fact in facts:
        label = PREDICATE_LABELS.get(str(fact.get("predicate") or ""), "")
        line = (
            f"[{fact.get('id')}] {fact.get('subject') or ''}{label}"
            f"{fact.get('object') or ''}（{format_date(fact.get('valid_from'))}）"
        )
        if total + len(line) > max_chars:
            break
        lines.append(line)
        total += len(line)
    body = "\n".join(lines)
    is_self = str(subject or "") in {"小雪", "千秋雪"}
    if is_self:
        voice = (
            "这是关于你【自己】的事实：用第一人称「我」写，"
            "不要写「小雪」「她」；不要把自己当成别人。"
        )
    else:
        voice = (
            "这是关于【对方】的事实：用第三人称「他/她」或对方的昵称写；"
            "绝对不要用「我」——「我」是你自己，不是对方。"
        )
    return f"""下面是关于「{subject}」的一组事实。请归纳 1~3 条“以后相处时真的用得上”的稳定认识，而不是复述事实。

输出 JSON：
{{"insights":[{{"scope":"other:{subject}","insight_type":"pattern","statement":"他感冒时更愿意被提醒吃药，不喜欢被催出门","confidence":0.8,"importance":0.7,"privacy":2,"evidence_fact_ids":[1,2],"reason":"..."}}]}}

insight_type 只能从：pattern / relationship / self / lesson / boundary（偏好已经由事实层记录，不要重复归纳）。
规则：
1. 每条洞察必须引用至少 2 条上面的事实 ID；只有 1 条证据的不要写。
2. 只写能跨时间复用的规律/偏好/相处方式；不要写“他今天做了什么”这种一次性事件。
3. 不确定就降低 confidence；不要把猜测写成事实。
4. privacy 取支撑事实里最严格的那一级。
5. 没有值得归纳的就输出 {{"insights":[]}}。
6. {voice}

事实：
{body}
"""


def extract_json_object(text: str) -> dict:
    """从模型输出里抠出 JSON 对象；失败返回空 dict。"""
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return {}
    candidate = raw[start : end + 1]
    try:
        data = json.loads(candidate)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def validate_insight(
    raw: dict,
    *,
    fact_ids: set[int],
    default_scope: str,
    aliases: dict | None = None,
    min_evidence: int = 3,
) -> dict | None:
    if not isinstance(raw, dict):
        return None
    statement = str(raw.get("statement") or "").strip()[:160]
    if len(statement) < 4:
        return None
    try:
        evidence = [int(item) for item in raw.get("evidence_fact_ids") or []]
    except (TypeError, ValueError):
        return None
    evidence = [item for item in evidence if item in fact_ids]
    if len(evidence) < max(1, int(min_evidence)):
        return None
    insight_type = str(raw.get("insight_type") or "pattern").strip().lower()
    if insight_type not in {"pattern", "relationship", "self", "lesson", "boundary"}:
        insight_type = "pattern"
    return {
        "scope": str(raw.get("scope") or default_scope)[:120],
        "insight_type": insight_type,
        "statement": statement,
        "confidence": _clamp(raw.get("confidence"), 0.05, 1.0, 0.6),
        "importance": _clamp(raw.get("importance"), 0.05, 1.0, 0.55),
        "privacy": int(_clamp(raw.get("privacy"), 0, 4, 2)),
        "evidence_fact_ids": evidence[:8],
    }
