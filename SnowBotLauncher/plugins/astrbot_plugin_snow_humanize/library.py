"""像个人：按语境决定这轮怎么回、回多长，并把回复拆成自然的气泡。

这里只有纯逻辑，不 import AstrBot，方便单测。核心是四件事：

- choose_mode：这轮是短回一句、先安慰、正经回答，还是普通聊天；
- style_hint：把“怎么回”写成一句注入给模型的话；
- shape_text：把模型回复按句子重新分组，变成 1~3 个气泡；
- update_state：记录她最近的回复长度和会话精力，避免连续几轮都是长篇。

拆气泡不依赖 AstrBot 的源码：每个气泡内部只保留最后一个句末标点，其余句号
换成逗号，这样 AstrBot 的分段正则（按“。？！”等切）仍会把一个气泡当成一段。
"""

from __future__ import annotations

import random
import re
import time

STYLE_MARK = "[怎么回]"
END_MARK = "[[对话结束]]"

SENTENCE_PUNCT = "。！？!?～~…"
CLOSERS = "”’\"'）)】」』"
SEGMENT_RE = re.compile(r".*?(?:\r?\n+|[。？！~…]+)|.+$", re.S | re.M)
URL_RE = re.compile(r"https?://[^\s，。！？；：、）】\"']+", re.I)
CODE_RE = re.compile(r"```|`[^`\n]+`")
TECH_RE = re.compile(
    r"(代码|报错|异常|错误|函数|接口|配置|安装|部署|命令|脚本|教程|步骤|"
    r"怎么|如何|为什么|是什么|区别|原理|推荐|帮我|查一下|翻译|多少|几点|"
    r"哪家|哪个好|能不能|可以吗|请问|有没有|是不是)",
    re.I,
)
EMOTION_RE = re.compile(
    r"(难受|难过|不开心|烦|累|疲惫|困|疼|痛|失眠|睡不着|感冒|发烧|咳嗽|"
    r"嗓子|头晕|恶心|压力|崩溃|委屈|想哭|害怕|焦虑|紧张|孤独|emo|"
    r"生病|医院|吃药|打针)"
)
AFFECTION_RE = re.compile(r"(想你|喜欢你|抱抱|亲亲|乖|辛苦|谢谢|晚安|早安|爱你)")
ADVICE_RE = re.compile(r"(记得|别忘了|别|不要|要|建议|一定|千万|按时|早点|好好|注意|尽量|最好)")
ACK_RE = re.compile(
    r"^(嗯+|哦+|噢+|喔+|好+|行+|对+|是+|哈+|嘿+|呵+|收到|懂了|知道了|"
    r"ok|okay|谢谢|晚安|早安|在吗|在么|？+|\?+|…+|\.{3,})$",
    re.I,
)
MARKER_RE = re.compile(r"\[\[[^\]]{1,20}\]\]|\[[^\]]{1,20}\]|&&[^&\r\n]{1,64}&&")


def _normalize(text: str) -> str:
    value = str(text or "").strip()
    value = MARKER_RE.sub("", value)
    return re.sub(r"[\s，。！？、,.!?~～…:：;；\"'“”‘’（）()\[\]【】<>《》\-]", "", value)


def is_ack(text: str) -> bool:
    """是不是“嗯/好/哈哈/收到/在吗”这类不需要展开的消息。"""
    value = str(text or "").strip()
    if not value:
        return True
    if ACK_RE.match(value):
        return True
    core = _normalize(value)
    return len(core) <= 3


def is_question(text: str) -> bool:
    value = str(text or "")
    if any(mark in value for mark in ("？", "?")):
        return True
    return bool(TECH_RE.search(value))


def is_technical(text: str) -> bool:
    value = str(text or "")
    return len(_normalize(value)) >= 8 and bool(TECH_RE.search(value))


def is_low_content(text: str) -> bool:
    """群聊里不值得专门接一句的内容。"""
    value = str(text or "").strip()
    return is_ack(value) or len(_normalize(value)) <= 4


def _protected_end(text: str, index: int) -> int | None:
    """如果 index 处在代码/链接/方括号/表情标记里，返回保护段结束位置。"""
    size = len(text)
    if text.startswith("```", index):
        end = text.find("```", index + 3)
        return size if end < 0 else end + 3
    if text[index] == "`":
        end = text.find("`", index + 1)
        return end + 1 if end >= 0 else None
    if text.startswith("http://", index) or text.startswith("https://", index):
        match = URL_RE.match(text, index)
        return match.end() if match else None
    if text.startswith("[[", index):
        end = text.find("]]", index + 2)
        return end + 2 if end >= 0 else None
    if text.startswith("&&", index):
        end = text.find("&&", index + 2)
        return end + 2 if end >= 0 and end < index + 70 else None
    if text[index] == "[":
        end = text.find("]", index + 1)
        return end + 1 if 0 <= end < index + 60 else None
    return None


def split_sentences(text: str) -> list[str]:
    """按句号/问号/叹号/换行切句，但不切代码、链接、表情和标记。"""
    value = str(text or "")
    result: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        sentence = "".join(buffer).strip()
        if sentence:
            result.append(sentence)
        buffer.clear()

    index = 0
    size = len(value)
    while index < size:
        protect_end = _protected_end(value, index)
        if protect_end is not None:
            buffer.append(value[index:protect_end])
            index = protect_end
            continue
        char = value[index]
        if char in "\r\n":
            flush()
            index += 1
            while index < size and value[index] in "\r\n":
                index += 1
            continue
        if char in SENTENCE_PUNCT:
            buffer.append(char)
            index += 1
            while index < size and value[index] in CLOSERS:
                buffer.append(value[index])
                index += 1
            flush()
            continue
        buffer.append(char)
        index += 1
    flush()
    return result


def _last_punct_index(text: str) -> int:
    last = -1
    index = 0
    size = len(text)
    while index < size:
        protect_end = _protected_end(text, index)
        if protect_end is not None:
            index = protect_end
            continue
        if text[index] in SENTENCE_PUNCT:
            last = index
        index += 1
    return last


def _one_segment(bubble: str, threshold: int) -> str:
    """让一个气泡在 AstrBot 的分段正则下只产生一段。"""
    text = str(bubble or "").strip()
    if not text:
        return ""
    if CODE_RE.search(text) or "&&" in text or END_MARK in text:
        return text
    text = re.sub(r"\s+", " ", text).strip()
    # 气泡够长时 AstrBot 本来就不分段，保留原来的语气标点。
    if len(text) > max(0, int(threshold)):
        return text
    last = _last_punct_index(text)
    run_start = last
    while run_start > 0 and text[run_start - 1] in SENTENCE_PUNCT:
        run_start -= 1
    pieces: list[str] = []
    index = 0
    size = len(text)
    while index < size:
        protect_end = _protected_end(text, index)
        if protect_end is not None:
            pieces.append(text[index:protect_end])
            index = protect_end
            continue
        char = text[index]
        if char in SENTENCE_PUNCT and index < run_start:
            pieces.append("，")
        else:
            pieces.append(char)
        index += 1
    merged = "".join(pieces)
    merged = re.sub(r"[，,]{2,}", "，", merged)
    merged = merged.strip("，, ")
    if not merged:
        return text
    # 句号后面还跟着引号/emoji 时，AstrBot 会把尾巴当成单独一段；
    # 去掉这个句号，整句就会走 ".+$" 分支，保持一个气泡。
    last = _last_punct_index(merged)
    if last >= 0 and merged[last + 1 :].strip():
        merged = merged[:last] + merged[last + 1 :]
    if len(SEGMENT_RE.findall(merged)) > 1:
        # 兜底：一个气泡里不留任何句末标点，避免被二次切开。
        pieces = []
        index = 0
        size = len(merged)
        while index < size:
            protect_end = _protected_end(merged, index)
            if protect_end is not None:
                pieces.append(merged[index:protect_end])
                index = protect_end
                continue
            char = merged[index]
            pieces.append("，" if char in SENTENCE_PUNCT else char)
            index += 1
        merged = re.sub(r"[，,]{2,}", "，", "".join(pieces)).strip("，, ")
    return merged or text


def _group_sentences(sentences: list[str], count: int) -> list[str]:
    sentences = [sentence for sentence in sentences if sentence.strip()]
    if not sentences:
        return []
    if count <= 1 or len(sentences) <= 1:
        return ["".join(sentences)]
    count = max(1, min(int(count), len(sentences)))
    total = sum(len(sentence) for sentence in sentences)
    bounds = [total * index / count for index in range(1, count)]
    groups: list[str] = []
    current: list[str] = []
    length = 0
    for sentence in sentences:
        current.append(sentence)
        length += len(sentence)
        if len(groups) < len(bounds) and length >= bounds[len(groups)]:
            groups.append("".join(current))
            current = []
    if current:
        groups.append("".join(current))
    return [group for group in groups if group.strip()]


def _truncate(sentences: list[str], limit: int) -> list[str]:
    """短回模式：只保留前一两句，别把关心和叮嘱都发出去。"""
    limit = max(8, int(limit))
    kept: list[str] = []
    total = 0
    for sentence in sentences:
        if kept and total + len(sentence) > limit:
            break
        kept.append(sentence)
        total += len(sentence)
        if total >= limit:
            break
    return kept or sentences[:1]


def _bubble_count(
    mode: str,
    sentence_count: int,
    total_chars: int,
    rng: random.Random,
    conf: dict | None = None,
) -> int:
    conf = conf or {}
    if mode == "short" or sentence_count <= 1:
        return 1
    if mode == "warm":
        if sentence_count >= 3 or total_chars > 60:
            return rng.choice((1, 2))
        return 1
    if mode == "answer":
        return 2 if sentence_count >= 4 or total_chars > 90 else 1
    two_chance = float(conf.get("two_bubble_chance", 0.35))
    three_chance = float(conf.get("three_bubble_chance", 0.1))
    if sentence_count == 2:
        return 2 if rng.random() < max(0.0, min(1.0, two_chance + 0.2)) else 1
    roll = rng.random()
    if roll < max(0.0, min(1.0, three_chance)):
        return 3
    if roll < max(0.0, min(1.0, three_chance + two_chance)):
        return 2
    return 1


def shape_text(
    text: str,
    *,
    mode: str = "normal",
    segment_threshold: int = 80,
    allow_bubbles: bool = True,
    short_max_chars: int = 45,
    conf: dict | None = None,
    rng: random.Random | None = None,
    bubble_count: int | None = None,
) -> list[str]:
    """把一条模型回复整理成 1~3 个气泡；返回空列表表示不改。"""
    value = str(text or "").strip()
    if not value:
        return []
    if END_MARK in value:
        return [value]
    # 代码块、列表和正经回答里的换行要保留，别为了拆气泡把格式揉成一团。
    if "```" in value or re.search(r"\n\s*(?:[-*•]|\d+[.、)])", value):
        return [value]
    if mode == "answer" and "\n" in value:
        return [value]
    sentences = split_sentences(value)
    if not sentences:
        return []
    # 代码和链接不截断，避免把有用的东西切掉。
    if mode == "short" and not URL_RE.search(value) and not CODE_RE.search(value):
        sentences = _truncate(sentences, short_max_chars)
    if not allow_bubbles:
        joined = "".join(sentences).strip()
        return [joined] if joined else []
    count = bubble_count
    if count is None:
        count = _bubble_count(
            mode,
            len(sentences),
            sum(len(sentence) for sentence in sentences),
            rng or random,
            conf,
        )
    count = max(1, min(int(count), 3 if mode != "short" else 1))
    groups = _group_sentences(sentences, count)
    bubbles = []
    for group in groups:
        bubble = _one_segment(group, segment_threshold)
        if bubble:
            bubbles.append(bubble)
    return bubbles


def new_state(now: float | None = None) -> dict:
    stamp = float(now if now is not None else time.time())
    return {
        "energy": 0.55,
        "warmth": 0.5,
        "long_streak": 0,
        "last_template": False,
        "last_reply_len": 0,
        "last_user_len": 0,
        "turns": 0,
        "updated": stamp,
    }


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def update_state(
    state: dict | None,
    *,
    user_text: str,
    reply_text: str,
    now: float | None = None,
) -> dict:
    """一轮结束后更新会话精力：连续短消息会变懒，长消息和撒娇会回一点精神。"""
    stamp = float(now if now is not None else time.time())
    current = dict(state or {})
    base = new_state(stamp)
    for key, value in base.items():
        current.setdefault(key, value)
    if stamp - float(current.get("updated") or 0) > 6 * 3600:
        current["energy"] = 0.55
        current["long_streak"] = 0
    text = str(user_text or "").strip()
    reply = str(reply_text or "").strip()
    core = _normalize(text)

    energy = float(current.get("energy", 0.55))
    warmth = float(current.get("warmth", 0.5))
    if is_ack(text) or len(core) <= 4:
        energy -= 0.06
    elif len(core) >= 20:
        energy += 0.04
    if EMOTION_RE.search(text):
        energy -= 0.04
        warmth += 0.05
    if AFFECTION_RE.search(text):
        warmth += 0.08
    warmth += (0.5 - warmth) * 0.08
    current["energy"] = _clamp(energy, 0.12, 0.95)
    current["warmth"] = _clamp(warmth, 0.12, 0.95)

    paragraphs = [item for item in re.split(r"\n\s*\n", reply) if item.strip()]
    templated = (
        len(paragraphs) >= 2
        and len(reply) >= 45
        and bool(ADVICE_RE.search(paragraphs[-1]))
    )
    current["last_template"] = templated
    if len(reply) >= 55 or templated:
        current["long_streak"] = int(current.get("long_streak") or 0) + 1
    else:
        current["long_streak"] = max(0, int(current.get("long_streak") or 0) - 1)
    current["last_reply_len"] = len(reply)
    current["last_user_len"] = len(core)
    current["turns"] = int(current.get("turns") or 0) + 1
    current["updated"] = stamp
    return current


def choose_mode(
    user_text: str,
    *,
    is_group: bool = False,
    addressed: bool = True,
    state: dict | None = None,
    rng: random.Random | None = None,
) -> str:
    """决定这一轮是 short / warm / answer / normal。"""
    rng = rng or random
    state = state or {}
    text = str(user_text or "").strip()
    core = _normalize(text)
    if not core:
        return "short"
    ack = is_ack(text)
    question = is_question(text)
    if EMOTION_RE.search(text) and not ack:
        return "warm"
    if is_technical(text) or (question and len(core) >= 8):
        return "answer"
    if ack:
        return "short"
    if is_group and not addressed and len(core) <= 20:
        return "short"
    if (
        int(state.get("long_streak") or 0) >= 2
        and not question
        and rng.random() < 0.45
    ):
        return "short"
    if (
        float(state.get("energy", 0.55)) < 0.3
        and not question
        and rng.random() < 0.5
    ):
        return "short"
    return "normal"


def _pick(rng: random.Random, options: tuple[str, ...]) -> str:
    return options[int(rng.random() * len(options)) % len(options)]


def style_hint(
    mode: str,
    state: dict | None = None,
    rng: random.Random | None = None,
) -> str:
    """生成一句很短的“这轮怎么回”，放在系统提示最后。"""
    rng = rng or random
    state = state or {}
    if mode == "short":
        body = _pick(
            rng,
            (
                "这轮就随口应一声：最多一句、20 字以内；不要给建议、不要反问、不要分两段，半句也行。",
                "这轮短一点，像手上正忙时回消息：一句就够，不解释、不总结、不铺垫。",
                "这轮别展开：回半句或者一个语气词都行，不要写成“关心+叮嘱”。",
            ),
        )
    elif mode == "warm":
        body = (
            "先接住对方的情绪，再聊半句；整条最多两句、一段话。"
            "不要写成“先关心、再叮嘱”的两段式，也别连着给建议。"
        )
    elif mode == "answer":
        body = (
            "这轮先把答案说清楚，2~3 句以内；不用表情、不卖萌、不额外关心，"
            "不要为了显得亲切加一段叮嘱。"
        )
    else:
        body = _pick(
            rng,
            (
                "像平时 QQ 聊天：1~2 句、一段话，只说一个重点；不要每次都给建议，不要总结，不要为了接话硬问问题。",
                "这轮可以只说自己的看法或刚在做的事，不用把对方每个点都回应到；一句也行。",
                "自然接一句就好，别用“先回应、再叮嘱”的两段式，也别每次都把话收得很完整。",
            ),
        )
    lines = [f"{STYLE_MARK} {body}"]
    if state.get("last_template"):
        lines.append("你上一条已经是“先关心、再叮嘱”的两段式，这次换个结构，别重复。")
    lines.append("这段只是写作要求，不要在回复里提到它。")
    return "\n".join(lines)
