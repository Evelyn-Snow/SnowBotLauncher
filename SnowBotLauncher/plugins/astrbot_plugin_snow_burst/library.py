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


# ---------------- QQ 小黄脸表情 ----------------
# AstrBot 的 message_str 不含 Face 组件：纯表情消息文本为空，主流程会当成
# 空消息直接跳过 LLM。这里把常见表情渲染成 [表情:名]，让她能看见。
# 映射只收录高置信的经典段；不在表里的表情按 [表情:id] 渲染，不猜名字。

FACE_NAMES = {
    # 全量 QQ 小黄脸名称表（来源：koishijs/QFace，NapCat 生成，2026-09 快照）
    0: "惊讶", 1: "撇嘴", 2: "色", 3: "发呆",
    4: "得意", 5: "流泪", 6: "害羞", 7: "闭嘴",
    8: "睡", 9: "大哭", 10: "尴尬", 11: "发怒",
    12: "调皮", 13: "呲牙", 14: "微笑", 15: "难过",
    16: "酷", 18: "抓狂", 19: "吐", 20: "偷笑",
    21: "可爱", 22: "白眼", 23: "傲慢", 24: "饥饿",
    25: "困", 26: "惊恐", 27: "流汗", 28: "憨笑",
    29: "悠闲", 30: "奋斗", 31: "咒骂", 32: "疑问",
    33: "嘘", 34: "晕", 35: "折磨", 36: "衰",
    37: "骷髅", 38: "敲打", 39: "再见", 41: "发抖",
    42: "爱情", 43: "跳跳", 46: "猪头", 49: "拥抱",
    53: "蛋糕", 55: "炸弹", 56: "刀", 59: "便便",
    60: "咖啡", 63: "玫瑰", 64: "凋谢", 66: "爱心",
    67: "心碎", 74: "太阳", 75: "月亮", 76: "赞",
    77: "踩", 78: "握手", 79: "胜利", 85: "飞吻",
    86: "怄火", 89: "西瓜", 96: "冷汗", 97: "擦汗",
    98: "抠鼻", 99: "鼓掌", 100: "糗大了", 101: "坏笑",
    102: "左哼哼", 103: "右哼哼", 104: "哈欠", 105: "鄙视",
    106: "委屈", 107: "快哭了", 108: "阴险", 109: "左亲亲",
    110: "吓", 111: "可怜", 112: "菜刀", 114: "篮球",
    116: "示爱", 118: "抱拳", 119: "勾引", 120: "拳头",
    121: "差劲", 122: "爱你", 123: "NO", 124: "OK",
    125: "转圈", 129: "挥手", 137: "鞭炮", 144: "喝彩",
    146: "爆筋", 147: "棒棒糖", 148: "喝奶", 169: "手枪",
    171: "茶", 172: "眨眼睛", 173: "泪奔", 174: "无奈",
    175: "卖萌", 176: "小纠结", 177: "喷血", 178: "斜眼笑",
    179: "doge", 180: "惊喜", 181: "戳一戳", 182: "笑哭",
    183: "我最美", 185: "羊驼", 187: "幽灵", 193: "大笑",
    194: "不开心", 198: "呃", 200: "求求", 201: "点赞",
    202: "无聊", 203: "托脸", 204: "吃", 206: "害怕",
    210: "飙泪", 211: "我不看", 212: "托腮", 214: "啵啵",
    215: "糊脸", 216: "拍头", 217: "扯一扯", 218: "舔一舔",
    219: "蹭一蹭", 221: "顶呱呱", 222: "抱抱", 223: "暴击",
    224: "开枪", 225: "撩一撩", 226: "拍桌", 227: "拍手",
    229: "干杯", 230: "嘲讽", 231: "哼", 232: "佛系",
    233: "掐一掐", 235: "颤抖", 237: "偷看", 238: "扇脸",
    239: "原谅", 240: "喷脸", 241: "生日快乐", 243: "甩头",
    244: "扔狗", 262: "脑阔疼", 263: "沧桑", 264: "捂脸",
    265: "辣眼睛", 266: "哦哟", 267: "头秃", 268: "问号脸",
    269: "暗中观察", 270: "emm", 271: "吃瓜", 272: "呵呵哒",
    273: "我酸了", 277: "汪汪", 278: "汗", 281: "无眼笑",
    282: "敬礼", 283: "狂笑", 284: "面无表情", 285: "摸鱼",
    286: "魔鬼笑", 287: "哦", 288: "请", 289: "睁眼",
    290: "敲开心", 292: "让我康康", 293: "摸锦鲤", 294: "期待",
    295: "拿到红包", 297: "拜谢", 298: "元宝", 299: "牛啊",
    300: "胖三斤", 301: "好闪", 302: "左拜年", 303: "右拜年",
    305: "右亲亲", 306: "牛气冲天", 307: "喵喵", 311: "打call",
    312: "变形", 314: "仔细分析", 317: "菜汪", 318: "崇拜",
    319: "比心", 320: "庆祝", 322: "拒绝", 323: "嫌弃",
    324: "吃糖", 325: "惊吓", 326: "生气", 332: "举牌牌",
    333: "烟花", 334: "虎虎生威", 336: "豹富", 337: "花朵脸",
    338: "我想开了", 339: "舔屏", 341: "打招呼", 342: "酸Q",
    343: "我方了", 344: "大怨种", 345: "红包多多", 346: "你真棒棒",
    347: "大展宏兔", 348: "福萝卜", 349: "坚强", 350: "贴贴",
    351: "敲敲", 352: "咦", 353: "拜托", 354: "尊嘟假嘟",
    355: "耶", 356: "666", 357: "裂开", 358: "骰子",
    359: "包剪锤", 360: "亲亲", 361: "狗狗笑哭", 362: "好兄弟",
    363: "狗狗可怜", 364: "超级赞", 365: "狗狗生气", 366: "芒狗",
    367: "狗狗疑问", 368: "奥特笑哭", 369: "彩虹", 370: "祝贺",
    371: "冒泡", 372: "气呼呼", 373: "忙", 374: "波波流泪",
    375: "超级鼓掌", 376: "跺脚", 377: "嗨", 378: "企鹅笑哭",
    379: "企鹅流泪", 380: "真棒", 381: "路过", 382: "emo",
    383: "企鹅爱心", 384: "晚安", 385: "太气了", 386: "呜呜呜",
    387: "太好笑", 388: "太头疼", 389: "太赞了", 390: "太头秃",
    391: "太沧桑", 392: "龙年快乐", 393: "新年中龙", 394: "新年大龙",
    395: "略略略", 396: "狼狗", 397: "抛媚眼", 398: "超级ok",
    399: "tui", 400: "快乐", 401: "超级转圈", 402: "别说话",
    403: "出去玩", 404: "闪亮登场", 405: "好运来", 406: "姐是女王",
    407: "我听听", 408: "臭美", 409: "送你花花", 410: "么么哒",
    411: "一起嗨", 412: "开心", 413: "摇起来", 415: "划龙舟",
    416: "中龙舟", 417: "大龙舟", 418: "填罐罐", 419: "火车",
    420: "中火车", 421: "大火车", 422: "粽于等到你", 423: "复兴号",
    424: "续标识", 425: "求放过", 426: "玩火", 427: "偷感",
    428: "收到", 429: "蛇年快乐", 430: "蛇身", 431: "蛇尾",
    432: "灵蛇献瑞", 433: "大鸽", 434: "鸽来了", 435: "关我鸟事",
    436: "跟鸽走", 437: "鸽鸽生气", 438: "可靠", 439: "鸽瞅瞅",
    440: "鸽喜欢", 441: "相信鸽", 442: "鸽王", 443: "戳一下",
    444: "超级6", 445: "比个心", 446: "超级心碎", 447: "太赞了",
    448: "放大招", 449: "+1", 450: "撇嘴", 451: "色",
    452: "微笑", 453: "发呆", 454: "得意", 455: "害羞",
    456: "闭嘴", 457: "睡", 458: "我吗", 459: "优雅",
    460: "硬撑", 461: "宕机", 462: "无语", 463: "新年快乐",
    464: "马上到", 465: "拆红包", 466: "羞羞哒", 467: "摇花手",
    468: "失眠", 469: "坚毅", 470: "马到成功", 471: "深情",
    472: "心动", 473: "爱意", 474: "给你一拳", 475: "干饭",
    476: "不是吧", 477: "你懂的", 478: "对的对的", 479: "不对不对",
    480: "散味儿", 481: "学习", 482: "热化了", 483: "略",
    484: "比爱心", 485: "开学啦", 486: "开学啦2", 487: "开学啦3",
    488: "开学大吉", 489: "知识增加", 490: "能送我吗", 491: "自信学霸",
    492: "让我细品", 493: "又是早八", 494: "举杯邀月", 495: "兔来",
    496: "阴晴圆缺", 497: "休假了", 498: "中!", 499: "观月C位",
    500: "秋秋赏月", 501: "秋秋之约", 502: "秋秋泛舟", 503: "秋愿达成",
    504: "同你玩", 505: "送花花", 506: "捡到宝了", 507: "被发现了",
}


def face_name(face_id) -> str:
    try:
        return FACE_NAMES.get(int(face_id), "")
    except (TypeError, ValueError):
        return ""


def face_label(face_id) -> str:
    try:
        face_id = int(face_id)
    except (TypeError, ValueError):
        return ""
    name = FACE_NAMES.get(face_id)
    return f"[表情:{name}]" if name else f"[表情:{face_id}]"


def render_face_ids(ids: list) -> str:
    """把一串表情 id 渲染成人话文本；空列表返回空串。"""
    labels = [face_label(fid) for fid in (ids or []) if face_label(fid)]
    return " ".join(labels)


# 名称 → id 反查（同名取最小 id），供模型用 [表情:名] 标记发真表情
FACE_IDS: dict[str, int] = {}
for _fid, _name in FACE_NAMES.items():
    FACE_IDS.setdefault(_name, _fid)

FACE_MARK_RE = re.compile(r"\[表情[:：]\s*([^\[\]]{1,12}?)\s*\]")


def split_face_markers(text: str) -> list[tuple[str, int | None]]:
    """把文本按 [表情:名] 标记切开，返回 [(文本段, None) / ("", 表情id), ...]。

    认不出的名字保持原样（fid=None 且文本段保留整个标记），不吞字。
    """
    raw = str(text or "")
    out: list[tuple[str, int | None]] = []
    pos = 0
    for match in FACE_MARK_RE.finditer(raw):
        if match.start() > pos:
            out.append((raw[pos : match.start()], None))
        fid = FACE_IDS.get(match.group(1).strip())
        if fid is None:
            out.append((match.group(0), None))
        else:
            out.append(("", fid))
        pos = match.end()
    if pos < len(raw):
        out.append((raw[pos:], None))
    return out or ([(raw, None)] if raw else [])


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


def merged_messages_hint(count: int, image_count: int = 0) -> str:
    """合流多条消息时给模型的说明：文字和图片当成一次表达，别逐条回答。"""
    count = max(2, int(count or 0))
    image_count = max(0, int(image_count or 0))
    if image_count:
        return (
            f"[连续消息] 对方刚才连续发了 {count} 条消息，其中包含 {image_count} 张图片；"
            "上面的文字是连在一起的同一段话，图片按原顺序附在消息里。"
            "请把文字和图片当成一次完整表达：按顺序对应着一起理解，"
            "不要只回文字、也不要只描述图片；不要逐条回答，也不要说“你发了好多条”。"
        )
    return (
        f"[连续消息] 对方刚才连续发了 {count} 条消息，"
        "上面用换行连在一起的是同一段话。请把它们当成一次表达，整体理解、一次回应；"
        "不要逐条回答，也不要说“你发了好多条”。如果中间夹着图片或表情，按顺序一起理解。"
    )
