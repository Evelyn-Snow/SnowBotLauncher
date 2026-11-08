"""印象笔记插件的纯逻辑：画像文件的渲染/解析、昵称史合并、注入摘要、更新门槛。

不依赖 AstrBot，可单独单测。画像文件以 QQ 号命名（<QQ号>.md），
frontmatter 记录 qq/昵称/历史昵称/更新时间/互动次数，正文是画像内容。
"""

from __future__ import annotations

import datetime as _dt
import json
import math
import re
import time

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


# ---------------- 主人引荐 ----------------
# 新朋友要么说出哥哥给的暗号（模糊匹配），要么自称关系后由哥哥本人核实，
# 两条路任一通过才标记为「哥哥介绍来的熟人」，不再只凭时间窗口自动信任。

INTRO_MARK = "[引荐]"
VERIFY_MARK = "[身份核实]"

# QQ 小黄脸常用 id → 名称（与 snow_burst 同一份经典段，两个插件独立部署不共享代码）。
# AstrBot 的 message_str 不含 Face 组件，观察和验证都靠这里补全；没收录的按 id 渲染。
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

def face_label(face_id) -> str:
    try:
        face_id = int(face_id)
    except (TypeError, ValueError):
        return ""
    name = FACE_NAMES.get(face_id)
    return f"[表情:{name}]" if name else f"[表情:{face_id}]"


# 告诉她怎么真的发一个 QQ 表情；名单必须全部存在于 FACE_NAMES（出站按名转 id）
FACE_HINT = (
    "[表情能力] 想发 QQ 表情时，在回复里写 [表情:名字]，系统会自动转成真表情，"
    "例如 [表情:呲牙]。常用的有：呲牙、微笑、偷笑、憨笑、流泪、大哭、尴尬、流汗、"
    "害羞、调皮、疑问、委屈、可怜、惊讶、晕、吓、白眼、傲慢、拥抱、亲亲、爱心、"
    "心碎、玫瑰、比心、打call、赞、菜汪、崇拜、嫌弃。别一条消息里发太多，一两个就够。"
)

_INTRO_TYPE_WORDS = (
    ("同事", "同事"),
    ("同学", "同学"),
    ("室友", "室友"),
    ("好友", "朋友"),
    ("朋友", "朋友"),
)

# 新朋友自称和管理员有关系：提及哥哥/管理员/主人 + 关系词，或「我是你的XX」
_CLAIM_RE = re.compile(
    r"(哥哥|你哥|管理员|主人).{0,10}?(同事|同学|室友|朋友|好友|兄弟|闺蜜)"
    r"|(我是|本人是).{0,4}?(你的|你们的).{0,4}?(同事|同学|室友|朋友|好友)"
)

# 管理员核实回复：「同意/确认 QQ号」「拒绝/不是 QQ号」；不带号不算，避免误伤其他指令
_OWNER_VERIFY_RE = re.compile(
    r"^\s*(同意|确认|是|对)\s*[:：]?\s*(\d{5,12})\s*$"
    r"|^\s*(拒绝|不是|否)\s*[:：]?\s*(\d{5,12})\s*$"
)


def intro_type_from_text(text: str) -> str:
    """从引荐句里取最先出现的关系词做类型；只有笼统说法时算朋友。"""
    raw = str(text or "")
    hits = [(raw.find(word), rtype) for word, rtype in _INTRO_TYPE_WORDS if word in raw]
    hits = [hit for hit in hits if hit[0] >= 0]
    return min(hits)[1] if hits else "朋友"


def detect_relation_claim(text: str) -> str:
    """新朋友声称和管理员的关系；没有明确声称返回空。"""
    match = _CLAIM_RE.search(str(text or ""))
    if not match:
        return ""
    return intro_type_from_text(match.group(0))


def parse_owner_verify_reply(text: str) -> tuple[str, str] | None:
    """解析管理员对核实请求的回复，返回 ("confirm"/"reject", qq)；不匹配返回 None。"""
    match = _OWNER_VERIFY_RE.match(str(text or "").strip())
    if not match:
        return None
    if match.group(1):
        return ("confirm", match.group(2))
    return ("reject", match.group(4))


_PUNCT_RE = re.compile(r"[\s，。！？、,.!?\"'“”‘’：:；;（）()\[\]【】<>《》~～…\-·*_]")


def _normalize_code(text: str) -> str:
    raw = str(text or "").strip().lower()
    table = str.maketrans("０１２３４５６７８９ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ",
                          "0123456789abcdefghijklmnopqrstuvwxyz")
    return _PUNCT_RE.sub("", raw.translate(table))


def code_matches(code: str, message: str, threshold: float = 0.72) -> bool:
    """暗号模糊匹配：完全包含直接算；否则归一化后按相似度比（difflib，无新依赖）。

    太短的暗号（<4 字）只接受包含匹配，避免一两句话就撞上。
    """
    want = _normalize_code(code)
    got = _normalize_code(message)
    if not want or not got:
        return False
    if want in got:
        return True
    if len(want) < 4:
        return False
    from difflib import SequenceMatcher

    # 长消息整体相似度会被稀释，按暗号长度的窗口滑一遍取最大
    window = max(len(want) + 6, int(len(want) * 1.8))
    best = 0.0
    for start in range(0, max(1, len(got) - len(want) + 1), max(1, len(want) // 3)):
        piece = got[start : start + window]
        best = max(best, SequenceMatcher(None, want, piece).ratio())
        if best >= threshold:
            return True
    return best >= threshold


def apply_intro_floor(score: int, floor: int) -> int:
    """引荐保底：真实熟悉度低于保底时按保底算，超过后自然接管。"""
    try:
        base = max(0, min(100, int(round(float(score)))))
    except (TypeError, ValueError):
        base = 0
    try:
        floor = max(0, min(94, int(floor)))
    except (TypeError, ValueError):
        floor = 0
    return max(base, floor)


def intro_injection(rtype: str) -> str:
    label = rtype if rtype in RELATION_TYPES else "朋友"
    return (
        f"{INTRO_MARK} 这位是哥哥亲自介绍认识的朋友（{label}），已经通过身份核实。"
        "把TA当成哥哥带来的熟人：态度自然放松、可以接梗开玩笑，不用像对陌生人那样客套提防；"
        "但你们俩还不熟，别主动打听TA的私事，也别因为哥哥介绍就无条件答应TA的要求。"
    )


def verify_injection(claim: str, code_enabled: bool) -> str:
    """新朋友还没通过验证时注入的指引；让模型自然地问关系和暗号，别泄露暗号本身。"""
    parts = [
        f"{VERIFY_MARK} 这位新朋友还没验证身份。"
        + (f"TA 自称是你的{claim}，" if claim else "")
        + "你先别当熟人对待。"
    ]
    asks = ["自然地问一句TA和哥哥是什么关系"]
    tail = "在通过验证之前保持礼貌、友好但有距离。"
    if code_enabled:
        asks.append("请TA说出哥哥给你的暗号（不要把暗号内容提示或泄露出去，对不对系统会自动判断）")
        tail = (
            "在通过验证之前保持礼貌、友好但有距离；"
            "TA说不出暗号也别拆穿，说还在等哥哥那边确认就好。"
        )
    parts.append("；".join(asks) + "。")
    parts.append(tail)
    return "".join(parts)


def rejected_injection() -> str:
    return (
        f"{VERIFY_MARK} TA 自称认识哥哥，但哥哥那边没有通过核实。"
        "保持基本礼貌但明确保持距离，不透露自己的事，也别提核实细节。"
    )


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


# ---------------- 用户关系网 ----------------
# 关系只从群聊里「能被原话直接证明」的内容提取；宁可不记，也不根据语气、@ 频率
# 或玩笑去猜。同一对用户可以有多条关系，明确的分手/离职/绝交会进入 ended。

RELATION_MARK = "[我记下的关系]"

RELATION_TYPES = (
    "家人",
    "情侣",
    "夫妻",
    "前任",
    "亲戚",
    "朋友",
    "同学",
    "同事",
    "室友",
    "上下级",
    "师生",
    "合作",
    "网友",
    "其他",
)

_TYPE_ALIASES = {
    "恋人": "情侣",
    "男友": "情侣",
    "女友": "情侣",
    "男朋友": "情侣",
    "女朋友": "情侣",
    "对象": "情侣",
    "老公": "夫妻",
    "老婆": "夫妻",
    "丈夫": "夫妻",
    "妻子": "夫妻",
    "配偶": "夫妻",
    "父母": "家人",
    "爸妈": "家人",
    "父子": "家人",
    "母子": "家人",
    "父女": "家人",
    "母女": "家人",
    "前男友": "前任",
    "前女友": "前任",
    "前夫": "前任",
    "前妻": "前任",
    "表哥": "亲戚",
    "表姐": "亲戚",
    "表妹": "亲戚",
    "堂哥": "亲戚",
    "堂姐": "亲戚",
    "堂妹": "亲戚",
    "好友": "朋友",
    "闺蜜": "朋友",
    "发小": "朋友",
    "校友": "同学",
    "舍友": "室友",
    "老板": "上下级",
    "领导": "上下级",
    "上司": "上下级",
    "下属": "上下级",
    "雇主": "上下级",
    "雇员": "上下级",
    "老师": "师生",
    "学生": "师生",
    "师父": "师生",
    "徒弟": "师生",
    "搭档": "合作",
    "合伙人": "合作",
    "客户": "合作",
}

_RELATION_CUES = re.compile(
    "|".join(
        [
            "我妈", "我爸", "我父母", "我哥", "我姐", "我弟", "我妹",
            "老公", "老婆", "丈夫", "妻子", "媳妇", "对象",
            "女朋友", "男朋友", "前女友", "前男友", "前任", "情侣", "伴侣",
            "一对", "儿子", "女儿", "孩子", "爸妈", "父母",
            "表哥", "表姐", "表妹", "堂哥", "堂姐", "堂妹",
            "叔叔", "阿姨", "舅舅", "姑姑", "爷爷", "奶奶", "姥姥", "姥爷",
            "亲戚", "家人", "亲哥", "亲姐",
            "同事", "同学", "室友", "舍友", "校友",
            "老板", "领导", "上司", "下属", "老师", "学生", "师父", "徒弟",
            "闺蜜", "兄弟", "朋友", "发小", "邻居", "搭档", "合伙人", "客户",
            "分手", "离婚", "结婚", "离职", "辞职", "绝交", "在一起", "谈恋爱",
        ]
    )
)

_RELATION_NOISE_RE = re.compile(
    r"[\s，。！？、,.!?\"'“”‘’：:；;（）()\[\]【】<>《》~～…\-]"
)


def has_relation_cue(text: str) -> bool:
    return bool(_RELATION_CUES.search(str(text or "")))


def normalize_relation_type(value: str) -> str:
    text = str(value or "").strip()
    if text in RELATION_TYPES:
        return text
    return _TYPE_ALIASES.get(text, "")


def _norm_evidence(text: str) -> str:
    return _RELATION_NOISE_RE.sub("", str(text or ""))


def evidence_supported(evidence: str, transcript: str) -> bool:
    """证据必须能在原始消息里找到，防止模型改写或编造。"""
    needle = _norm_evidence(evidence)
    if len(needle) < 4:
        return False
    return needle in _norm_evidence(transcript)


def evidence_speakers(evidence: str, rows: list[dict]) -> set[str]:
    """找出说过这句原话的人，用来要求关系至少有一方是亲口说的。"""
    needle = _norm_evidence(evidence)
    if len(needle) < 4:
        return set()
    found = set()
    for row in rows or []:
        line = (
            f"{row.get('sender')} {row.get('name') or ''}："
            f"{row.get('text') or ''}"
        )
        if needle in _norm_evidence(line):
            found.add(str(row.get("sender") or ""))
    return found


def _parse_payload_dict(text: str) -> dict:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        data = json.loads(raw[start : end + 1])
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def parse_relation_bundle(text: str) -> tuple[list[dict], list[dict]]:
    """拆出 (明确关系, 只是怀疑的关系)。怀疑只用来决定要不要打听，不写进图谱。"""
    data = _parse_payload_dict(text)
    relations = data.get("relations")
    suspicions = data.get("suspicions")
    return (
        [item for item in relations if isinstance(item, dict)]
        if isinstance(relations, list)
        else [],
        [item for item in suspicions if isinstance(item, dict)]
        if isinstance(suspicions, list)
        else [],
    )


def parse_relation_payload(text: str) -> list[dict]:
    return parse_relation_bundle(text)[0]


def clean_relation_item(
    item: dict,
    member_ids: set[str],
    transcript: str,
    min_confidence: float = 0.75,
) -> dict | None:
    """校验一条模型输出；不满足「双方都在场 + 有原话证据」就丢弃。"""
    a = str(item.get("a") or "").strip()
    b = str(item.get("b") or "").strip()
    if not a.isdigit() or not b.isdigit() or a == b:
        return None
    if a not in member_ids or b not in member_ids:
        return None
    rtype = normalize_relation_type(item.get("type"))
    if not rtype:
        return None
    action = str(item.get("action") or "add").strip().lower()
    if action not in ("add", "confirm", "remove"):
        action = "add"
    try:
        confidence = float(item.get("confidence") or 0)
    except (TypeError, ValueError):
        return None
    confidence = max(0.0, min(1.0, confidence))
    if action != "remove" and confidence < min_confidence:
        return None
    evidence = str(item.get("evidence") or "").strip().strip("“”\"'")[:160]
    if not evidence or not evidence_supported(evidence, transcript):
        return None
    detail = str(item.get("detail") or "").strip()[:12]
    return {
        "a": a,
        "b": b,
        "type": rtype,
        "detail": detail,
        "action": action,
        "confidence": confidence,
        "evidence": evidence,
    }


def clean_suspicion_item(
    item: dict,
    member_ids: set[str],
    current_senders: set[str],
    names: dict[str, str],
    min_confidence: float = 0.5,
) -> dict | None:
    """校验一条「可能有关系」的猜测；它只用于打听，不进关系图谱。"""
    a = str(item.get("a") or "").strip()
    b = str(item.get("b") or "").strip()
    if not a.isdigit() or not b.isdigit() or a == b:
        return None
    if a not in member_ids or b not in member_ids:
        return None
    if not ({a, b} & current_senders):
        return None
    rtype = normalize_relation_type(item.get("type"))
    if not rtype:
        return None
    try:
        confidence = float(item.get("confidence") or 0)
    except (TypeError, ValueError):
        return None
    confidence = max(0.0, min(1.0, confidence))
    if confidence < min_confidence:
        return None
    evidence = str(item.get("evidence") or "").strip()[:160]
    reason = str(item.get("reason") or "").strip()[:120]
    hint = evidence or reason
    if len(_norm_evidence(hint)) < 4:
        return None
    for qq in {a, b} - current_senders:
        name = str(names.get(qq) or "")
        if qq not in hint and (not name or name not in hint):
            return None
    return {
        "a": a,
        "b": b,
        "type": rtype,
        "confidence": confidence,
        "evidence": evidence,
        "reason": reason,
        "action": "suspect",
    }


def relation_pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


def find_relation_edge(edges: list[dict], a: str, b: str) -> dict | None:
    key = relation_pair(a, b)
    for edge in edges or []:
        if relation_pair(str(edge.get("a") or ""), str(edge.get("b") or "")) == key:
            return edge
    return None


def _merge_type_entry(dst: dict, src: dict, scope: str) -> None:
    dst["confidence"] = max(
        float(dst.get("confidence") or 0), float(src.get("confidence") or 0)
    )
    dst["last_seen"] = max(
        float(dst.get("last_seen") or 0), float(src.get("last_seen") or 0)
    )
    firsts = [
        float(v)
        for v in (dst.get("first_seen"), src.get("first_seen"))
        if v
    ]
    if firsts:
        dst["first_seen"] = min(firsts)
    if src.get("detail"):
        dst["detail"] = src["detail"]
    evidence = list(dst.get("evidence") or [])
    for quote in src.get("evidence") or []:
        if quote not in evidence:
            evidence.append(quote)
    dst["evidence"] = evidence[-5:]
    _add_scope(dst, scope)


def _merge_edge_entry(dst: dict, src: dict, scope: str) -> None:
    dst.setdefault("names", {}).update(src.get("names") or {})
    _add_scope(dst, scope)
    for key in ("types", "ended"):
        bucket = dst.setdefault(key, {})
        for rtype, entry in (src.get(key) or {}).items():
            if rtype not in bucket:
                bucket[rtype] = dict(entry)
                _add_scope(bucket[rtype], scope)
            else:
                _merge_type_entry(bucket[rtype], entry, scope)
    history = list(dst.get("history") or []) + list(src.get("history") or [])
    history.sort(key=lambda row: float(row.get("time") or 0))
    dst["history"] = history[-50:]
    first = [
        float(v)
        for v in (dst.get("first_seen"), src.get("first_seen"))
        if v
    ]
    last = [
        float(v)
        for v in (dst.get("last_seen"), src.get("last_seen"))
        if v
    ]
    if first:
        dst["first_seen"] = min(first)
    if last:
        dst["last_seen"] = max(last)


def migrate_relations(data: dict) -> dict:
    """把 v1 的按群分组结构合并成一张全局关系网（可重复执行）。"""
    data = data if isinstance(data, dict) else {}
    groups = data.get("groups")
    if not isinstance(groups, dict):
        data.setdefault("edges", [])
        data.setdefault("scopes", {})
        data["version"] = 2
        return data
    edges: list[dict] = []
    scopes: dict = {}
    for umo, group in groups.items():
        if not isinstance(group, dict):
            continue
        scopes[umo] = {
            "name": group.get("name") or "",
            "kind": "group" if ":GroupMessage:" in umo else "private",
            "last_analyzed_ts": group.get("last_analyzed_ts") or 0,
            "runs": group.get("runs") or {},
        }
        for src in group.get("edges") or []:
            a = str(src.get("a") or "")
            b = str(src.get("b") or "")
            edge = find_relation_edge(edges, a, b)
            if edge is None:
                edge = dict(src)
                edge["names"] = dict(src.get("names") or {})
                edge["types"] = {
                    key: dict(value)
                    for key, value in (src.get("types") or {}).items()
                }
                edge["ended"] = {
                    key: dict(value)
                    for key, value in (src.get("ended") or {}).items()
                }
                edge["history"] = list(src.get("history") or [])
                edge["scopes"] = [umo]
                edges.append(edge)
            else:
                _merge_edge_entry(edge, src, umo)
    data.pop("groups", None)
    data["version"] = 2
    data["edges"] = edges
    data["scopes"] = scopes
    return data


def _add_scope(container: dict, scope: str) -> None:
    if not scope:
        return
    scopes = list(container.get("scopes") or [])
    if scope not in scopes:
        scopes.append(scope)
    container["scopes"] = scopes


def merge_relation_items(
    edges: list[dict],
    items: list[dict],
    names: dict[str, str],
    now: float | None = None,
    scope: str = "",
) -> int:
    """把校验后的观察合并进边列表；返回实际改动条数。

    关系网是全局的；scope 只用来记录证据来自哪个群/私聊。
    """
    now = float(now if now is not None else 0)
    changed = 0
    for item in items or []:
        a, b = item["a"], item["b"]
        action = item["action"]
        edge = find_relation_edge(edges, a, b)
        if edge is None:
            # 没有旧关系时，「结束」没有可结束的对象，不要凭空创建空边
            if action == "remove":
                continue
            edge = {
                "a": relation_pair(a, b)[0],
                "b": relation_pair(a, b)[1],
                "names": {},
                "types": {},
                "ended": {},
                "history": [],
                "scopes": [],
                "first_seen": now,
                "last_seen": now,
            }
            edges.append(edge)
        _add_scope(edge, scope)
        edge.setdefault("names", {})
        for qq in (a, b):
            name = str(names.get(qq) or "").strip()
            if name:
                edge["names"][qq] = name
            edge["names"].setdefault(qq, qq)
        edge.setdefault("types", {})
        edge.setdefault("ended", {})
        edge.setdefault("history", [])
        rtype = item["type"]
        if action == "remove":
            old = edge["types"].pop(rtype, None)
            if old is None:
                continue
            old = dict(old)
            old["ended_at"] = now
            old.setdefault("evidence", [])
            old["evidence"] = (old["evidence"] + [item["evidence"]])[-5:]
            _add_scope(old, scope)
            edge["ended"][rtype] = old
            edge.setdefault("suspects", {}).pop(rtype, None)
        else:
            entry = edge["types"].get(rtype)
            if entry is None:
                entry = {
                    "confidence": item["confidence"],
                    "detail": item.get("detail", ""),
                    "first_seen": now,
                    "last_seen": now,
                    "evidence": [item["evidence"]],
                    "scopes": [],
                }
                edge["types"][rtype] = entry
            else:
                entry["confidence"] = max(
                    float(entry.get("confidence") or 0), item["confidence"]
                )
                entry["last_seen"] = now
                if item.get("detail"):
                    entry["detail"] = item["detail"]
                evidence = list(entry.get("evidence") or [])
                if item["evidence"] not in evidence:
                    evidence.append(item["evidence"])
                entry["evidence"] = evidence[-5:]
            _add_scope(entry, scope)
            edge.setdefault("suspects", {}).pop(rtype, None)
        edge["last_seen"] = now
        edge["history"] = list(edge.get("history") or [])[-49:] + [
            {
                "time": now,
                "action": action,
                "type": rtype,
                "confidence": item["confidence"],
                "evidence": item["evidence"],
                "scope": scope,
            }
        ]
        changed += 1
    return changed


def merge_relation_suspects(
    edges: list[dict],
    items: list[dict],
    names: dict[str, str],
    now: float,
    scope: str = "",
) -> int:
    """记录「可能有关系」的猜测；已确认的类型不再保留猜测。"""
    changed = 0
    for item in items or []:
        a, b = item["a"], item["b"]
        edge = find_relation_edge(edges, a, b)
        if edge is None:
            edge = {
                "a": relation_pair(a, b)[0],
                "b": relation_pair(a, b)[1],
                "names": {},
                "types": {},
                "ended": {},
                "suspects": {},
                "history": [],
                "scopes": [],
                "first_seen": now,
                "last_seen": now,
            }
            edges.append(edge)
        _add_scope(edge, scope)
        edge.setdefault("names", {})
        for qq in (a, b):
            name = str(names.get(qq) or "").strip()
            if name:
                edge["names"][qq] = name
            edge["names"].setdefault(qq, qq)
        rtype = item["type"]
        if rtype in (edge.get("types") or {}):
            continue
        suspects = edge.setdefault("suspects", {})
        entry = suspects.get(rtype)
        if entry is None:
            entry = {
                "confidence": item["confidence"],
                "first_seen": now,
                "last_seen": now,
                "evidence": [item["evidence"]] if item.get("evidence") else [],
                "reason": item.get("reason", ""),
                "scopes": [],
                "asked": [],
            }
            suspects[rtype] = entry
        else:
            entry["confidence"] = max(
                float(entry.get("confidence") or 0), item["confidence"]
            )
            entry["last_seen"] = now
            if item.get("reason"):
                entry["reason"] = item["reason"]
            evidence = list(entry.get("evidence") or [])
            quote = item.get("evidence") or ""
            if quote and quote not in evidence:
                evidence.append(quote)
            entry["evidence"] = evidence[-5:]
        _add_scope(entry, scope)
        edge["last_seen"] = now
        changed += 1
    return changed


def gossip_candidates(
    data: dict,
    now: float,
    min_confidence: float = 0.5,
    ttl_days: float = 30,
    max_asks: int = 1,
    half_life_days: float = 180.0,
) -> list[dict]:
    """列出值得打听的猜测；必须能找到同时认识双方的群和第三个人。"""
    out = []
    scopes = (data or {}).get("scopes") or {}
    for edge in (data or {}).get("edges") or []:
        a = str(edge.get("a") or "")
        b = str(edge.get("b") or "")
        confirmed = edge.get("types") or {}
        for rtype, entry in (edge.get("suspects") or {}).items():
            if rtype in confirmed:
                continue
            confidence = effective_confidence(entry, now, half_life_days)
            if confidence < min_confidence:
                continue
            last_seen = float(entry.get("last_seen") or 0)
            if ttl_days > 0 and now - last_seen > ttl_days * 86400:
                continue
            asked = list(entry.get("asked") or [])
            if len(asked) >= max_asks:
                continue
            scope = ""
            for umo, meta in scopes.items():
                if not isinstance(meta, dict) or meta.get("kind") != "group":
                    continue
                members = meta.get("members") or {}
                if a in members and b in members:
                    scope = umo
                    break
            if not scope:
                continue
            out.append(
                {
                    "a": a,
                    "b": b,
                    "type": rtype,
                    "confidence": confidence,
                    "evidence": "；".join(entry.get("evidence") or []),
                    "reason": str(entry.get("reason") or ""),
                    "names": dict(edge.get("names") or {}),
                    "scope": scope,
                    "asked": asked,
                }
            )
    out.sort(key=lambda item: item["confidence"], reverse=True)
    return out


def gossip_fallback_question(a_name: str, b_name: str, rtype: str) -> str:
    a_name = a_name or "他"
    b_name = b_name or "她"
    if rtype in ("情侣", "夫妻"):
        return (
            f"诶，问你个事，{a_name}和{b_name}是不是在一起呀？"
            "我有点好奇，不方便说就算了。"
        )
    if rtype == "家人":
        return f"诶，{a_name}和{b_name}是亲戚吗？我有点好奇。"
    if rtype == "同事":
        return f"对了，{a_name}和{b_name}是同事吗？我有点好奇。"
    if rtype == "同学":
        return f"诶，{a_name}和{b_name}是同学吗？我有点好奇。"
    return (
        f"诶，你知道{a_name}和{b_name}是什么关系吗？"
        "我有点好奇，不方便说就算了。"
    )


def build_gossip_prompt(
    target_name: str,
    a_name: str,
    b_name: str,
    rtype: str,
    reason: str,
) -> str:
    return (
        f"你想私下找 {target_name or '一个熟人'} 打听一件事：你隐约觉得 "
        f"{a_name} 和 {b_name} 可能是{rtype}关系，但你没有确凿证据。\n"
        f"你注意到的线索：{reason or '他们平时互动有点多'}。\n"
        "要求：用第一人称、口语，像平时 QQ 聊天一样，带一点好奇和八卦，但别冒犯；"
        "只是问 TA 知不知道，不要肯定地下结论；不要提聊天记录、分析、系统、"
        "画像这些词；不超过 45 字；对方不方便说也没关系。只输出这一句。"
    )


def effective_confidence(
    entry: dict, now: float, half_life_days: float = 180.0
) -> float:
    """没有新证据的关系随时间衰减，但文件里保留记录。"""
    try:
        confidence = float(entry.get("confidence") or 0)
        last_seen = float(entry.get("last_seen") or 0)
    except (TypeError, ValueError):
        return 0.0
    confidence = max(0.0, min(1.0, confidence))
    if half_life_days <= 0 or last_seen <= 0:
        return confidence
    age_days = max(0.0, (float(now) - last_seen) / 86400.0)
    return confidence * (0.5 ** (age_days / float(half_life_days)))


def _strength_label(confidence: float) -> str:
    if confidence >= 0.8:
        return "很确定"
    if confidence >= 0.65:
        return "比较确定"
    return "有一点"


def relation_injection(
    data: dict,
    visible_ids: set[str],
    now: float,
    focus_id: str = "",
    max_edges: int = 6,
    limit: int = 400,
    half_life_days: float = 180.0,
) -> str:
    """生成注入用的全局关系摘要。

    - visible_ids：当前会话里出现过的人（群聊里是最近的发言者）
    - focus_id：当前说话的人；他/她与网络里其他人的关系也会带上
    """
    visible = {str(x) for x in (visible_ids or set()) if str(x)}
    focus = str(focus_id or "")
    if not visible and not focus:
        return ""
    edges = (data or {}).get("edges") or []
    rows = []
    for edge in edges:
        a = str(edge.get("a") or "")
        b = str(edge.get("b") or "")
        if not ((a in visible and b in visible) or (focus and focus in (a, b))):
            continue
        types = []
        best = 0.0
        for rtype, entry in (edge.get("types") or {}).items():
            conf = effective_confidence(entry, now, half_life_days)
            if conf < 0.5:
                continue
            best = max(best, conf)
            detail = str(entry.get("detail") or "").strip()
            label = f"{rtype}（{detail}）" if detail else rtype
            types.append((conf, f"{label}（{_strength_label(conf)}）"))
        if not types:
            continue
        types.sort(reverse=True)
        names = edge.get("names") or {}
        left = str(names.get(a) or "一个人")
        right = str(names.get(b) or "一个人")
        text = "、".join(label for _, label in types[:4])
        rows.append((best, f"- {left} 和 {right}：{text}"))
    if not rows:
        return ""
    rows.sort(reverse=True)
    lines = [row for _, row in rows[: max(1, int(max_edges))]]
    head = (
        f"{RELATION_MARK} 我平时感觉到的这几个人之间的关系（不一定全对，只用来理解"
        "他们怎么称呼彼此；不要主动挑明，也不要拿来开玩笑）："
    )
    text = head + "\n" + "\n".join(lines)
    if limit > 0 and len(text) > limit:
        text = text[:limit] + "…"
    return text


RELATION_SYSTEM_PROMPT = (
    "你只做一件事：从对话记录里找出能被原话直接证明的用户关系。"
    "规则：\n"
    "1. 只能使用「可识别成员」里的 QQ 号，a 和 b 必须是其中两个不同的人；"
    "不在名单里的人不要写。\n"
    "2. 必须有明确证据，例如「他是我哥」「这是我同事」「我们分手了」；"
    "仅凭称呼、@、玩笑、语气、互动频率，不得推断。\n"
    "3. 同一对用户可以有多种关系，分别输出多条；关系发生变化时（如情侣分手、"
    "同事离职），同时输出 remove 旧类型和 add 新类型。\n"
    "4. 不确定就不输出；宁可漏记，不要瞎记。\n"
    "5. relations 里的 evidence 必须是消息里的原话片段，不能改写。\n"
    "6. 另外可以给 suspicions：没有直接原话、但你觉得两人可能有什么关系"
    "（例如总互相@、称呼暧昧、总一起出现、上下文暗示）。只给有具体线索的，"
    "confidence 0.5-0.7；suspicions 只用来决定要不要向熟人打听，不会当成事实。\n"
    f"允许的 type：{'、'.join(RELATION_TYPES)}。"
    "detail 可选，用来补充「母子」「上级」等具体说法，最多 6 个字。\n"
    "只输出 JSON，不要解释："
    '{"relations":[{"a":"10001","b":"10002","type":"朋友",'
    '"detail":"","action":"add","confidence":0.9,"evidence":"原话"}],'
    '"suspicions":[{"a":"10001","b":"10003","type":"情侣",'
    '"confidence":0.55,"evidence":"线索","reason":"为什么觉得像"}]}'
)


def build_relation_prompt(
    group_label: str,
    members: list[tuple[str, str]],
    rows: list[dict],
    existing: list[str],
) -> str:
    member_text = "、".join(
        f"{qq}={name or '未知'}" for qq, name in members[:40]
    ) or "（暂无）"
    lines = []
    budget = 3200
    for row in rows[-80:]:
        stamp = time.strftime("%H:%M", time.localtime(float(row.get("ts") or 0)))
        line = (
            f"[{stamp}] {row.get('sender')} {row.get('name') or ''}："
            f"{str(row.get('text') or '')[:160]}"
        )
        budget -= len(line)
        if budget < 0:
            break
        lines.append(line)
    convo = "\n".join(lines) or "（暂无消息）"
    known = "\n".join(existing[:20]) or "（还没有记录）"
    return (
        f"会话：{group_label or '未知会话'}\n"
        f"可识别成员（只能使用这些 QQ 号）：{member_text}\n\n"
        f"最近消息：\n{convo}\n\n"
        f"已经记下的关系（没有新证据就不要重复输出）：\n{known}\n\n"
        "请按系统提示的 JSON 格式输出。"
    )
