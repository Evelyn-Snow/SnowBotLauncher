"""snow_imagine 的纯逻辑：构图选择、场景清洗、衣橱匹配与提示词拼装。

核心原则：
- 不是每张图都要她出镜，也不是每张都以她为中心；
- 允许其他人物、动态模糊、跑出画面、手抖抓拍；
- 角色一致性只在“她出镜”时用 character_ref；
- 场景描述先脱敏，再交给外部图像服务。
"""

from __future__ import annotations

import random
import re

COMPOSITIONS = ("scene", "partial", "candid", "group", "portrait")

COMPOSITION_LABELS = {
    "scene": "只拍场景/物件，她不出镜",
    "partial": "局部出镜（手/背影/侧脸/画面边缘）",
    "candid": "抓拍动态（模糊/跑出画面/手抖）",
    "group": "人群中的她（其他人物在背景）",
    "portrait": "正面半身/立绘（仅在明确要求时）",
}

SHOT_PRESETS = {
    "rule_of_thirds": "rule-of-thirds composition, subject off-center, generous negative space",
    "leading_lines": "strong leading lines guiding the eye toward the subject, corridor or desk lines",
    "over_shoulder": "over-the-shoulder shot, foreground shoulder and hair softly blurred",
    "pov": "first-person POV, hands and objects in the lower frame, immersive viewpoint",
    "closeup": "close-up detail shot, shallow depth of field, soft blurred background",
    "wide": "wide establishing shot, character small in the environment, environment dominant",
    "low_angle": "low-angle shot, dynamic perspective, slight upward view",
    "high_angle": "high-angle tabletop shot, looking down at desk, food or hands",
    "framed": "framed composition through a window or doorway, natural vignette",
    "reflection": "reflection in glass or water, face not necessarily visible, layered composition",
    "backlit": "backlit subject, rim light on hair, slightly overexposed highlights",
    "motion_blur": "slow shutter, motion blur, panning shot, movement trails",
    "flash": "direct flash snapshot, candid, slightly harsh light, everyday imperfection",
    "film": "film grain, polaroid color shift, soft contrast, snapshot feel",
}

SHOT_LABELS = {
    "rule_of_thirds": "三分法",
    "leading_lines": "引导线",
    "over_shoulder": "过肩",
    "pov": "第一人称 POV",
    "closeup": "特写",
    "wide": "广角环境",
    "low_angle": "低角度",
    "high_angle": "高角度/俯拍",
    "framed": "窗框/门框",
    "reflection": "反射",
    "backlit": "逆光",
    "motion_blur": "动态模糊",
    "flash": "直闪抓拍",
    "film": "胶片感",
}

EXPRESSION_PROMPTS = {
    "smile": "gentle soft smile",
    "sleepy": "sleepy half-closed eyes, small yawn",
    "proud": "playful proud smirk with a slight wink",
    "shy": "shy blush, looking away",
    "surprised": "surprised wide eyes, mouth slightly open",
    "pouty": "pouty puffed cheeks, cute annoyed expression",
    "teary": "teary eyes, slightly downturned mouth, not fully crying",
    "thinking": "deadpan thinking, resting cheek on one hand",
    "laughing": "bright laughing, eyes curved, happy",
    "worried": "worried frown, slightly furrowed brows",
    "focused": "focused serious expression, concentrated",
    "soft": "relaxed absent-minded gaze, soft expression",
    "embarrassed": "embarrassed, covering face with one hand",
    "deadpan": "deadpan unimpressed look, half-lidded eyes",
}

EXPRESSION_LABELS = {
    "smile": "微笑",
    "sleepy": "困",
    "proud": "得意",
    "shy": "害羞",
    "surprised": "惊讶",
    "pouty": "鼓腮生气",
    "teary": "委屈",
    "thinking": "托腮/思考",
    "laughing": "大笑",
    "worried": "担心",
    "focused": "认真",
    "soft": "发呆",
    "embarrassed": "害羞捂脸",
    "deadpan": "无语",
}

_PORTRAIT_WORDS = ("自拍", "正脸", "你长什么样", "看看你", "你的脸", "立绘", "半身", "照片给我")
_GROUP_WORDS = ("朋友", "同学", "同事", "大家", "人群", "聚会", "一起", "合照")
_MOTION_WORDS = ("跑", "走", "回头", "抓拍", "动态", "冲", "跳", "骑车", "赶", "追")
_OBJECT_WORDS = ("书桌", "桌面", "书", "手账", "画纸", "画", "饭", "餐", "咖啡", "茶", "天空", "窗外", "校园", "教室", "床", "台灯")
_SENSITIVE_RE = re.compile(
    r"密码|验证码|身份证|银行卡|工资|收入|病历|裸照|自杀|自残|"
    r"(?<!\d)\d{5,12}(?!\d)"
)
_URL_RE = re.compile(r"https?://\S+", re.I)
_PATH_RE = re.compile(r"[A-Za-z]:\\[^\s，。]+")


def sanitize_scene(text: str, max_chars: int = 200) -> str:
    """去掉 QQ 号、链接、路径和敏感信息；命中敏感词返回空串。"""
    value = str(text or "").strip()
    if not value:
        return ""
    if _SENSITIVE_RE.search(value):
        return ""
    value = _URL_RE.sub("", value)
    value = _PATH_RE.sub("", value)
    value = re.sub(r"\s+", " ", value).strip(" ，。;；")
    return value[:max_chars]


def choose_composition(
    scene: str,
    requested: str = "auto",
    *,
    allow_portrait: bool = True,
    rng: random.Random | None = None,
) -> str:
    """选择构图；auto 时优先根据场景关键词判断，不默认正脸。"""
    rng = rng or random
    value = str(requested or "auto").strip().lower()
    if value in COMPOSITIONS:
        if value == "portrait" and not allow_portrait:
            return "partial"
        return value
    text = str(scene or "")
    if any(word in text for word in _PORTRAIT_WORDS):
        return "portrait" if allow_portrait else "partial"
    if any(word in text for word in _GROUP_WORDS):
        return "group"
    if any(word in text for word in _MOTION_WORDS):
        return "candid"
    if any(word in text for word in _OBJECT_WORDS):
        return "scene"
    # 默认：场景/局部为主，抓拍其次，不默认正脸
    return rng.choices(
        ("scene", "partial", "candid", "group"),
        weights=(0.4, 0.3, 0.2, 0.1),
        k=1,
    )[0]


def wardrobe_for_scene(spec: dict, scene: str, outfit: str = "auto") -> dict:
    """按场景/显式 outfit 从衣橱里挑一套；没有匹配就日常。"""
    wardrobe = spec.get("wardrobe") or {}
    requested = str(outfit or "auto").strip().lower()
    if requested in wardrobe:
        value = wardrobe.get(requested) or {}
        return dict(value) if isinstance(value, dict) else {}
    text = str(scene or "")
    if any(word in text for word in ("雨", "伞")):
        key = "rainy_day"
    elif any(word in text for word in ("跑", "运动", "操场", "健身")):
        key = "sport"
    elif any(word in text for word in ("夏", "热", "短袖")):
        key = "summer"
    elif ("雪" in text and "夜" in text) or any(
        word in text for word in ("正式", "晚宴", "表演")
    ):
        key = "snow_night" if ("雪" in text or "夜" in text) and "snow_night" in wardrobe else "formal"
    elif any(word in text for word in ("雪", "冬", "冷", "围巾")):
        key = "winter"
    elif any(word in text for word in ("夜", "睡前", "晚安")):
        key = "sleepwear"
    elif any(word in text for word in ("画", "颜料", "速写", "水彩")):
        key = "art"
    elif any(word in text for word in ("图书馆", "自习", "考试")):
        key = "library"
    elif any(word in text for word in ("居家", "宿舍", "书桌", "手账", "床")):
        key = "home_study"
    else:
        key = "daily_campus"
    value = wardrobe.get(key) or wardrobe.get("daily_campus") or {}
    if not value and spec.get("daily_default"):
        value = spec["daily_default"]
    return dict(value) if isinstance(value, dict) else {}


def choose_shot(
    scene: str,
    requested: str = "auto",
    *,
    composition: str = "scene",
    rng: random.Random | None = None,
) -> str:
    """选一个摄影取景预设；auto 按构图类型挑，不总是正面平视。"""
    rng = rng or random
    value = str(requested or "auto").strip().lower()
    if value in SHOT_PRESETS:
        return value
    pools = {
        "scene": ("high_angle", "closeup", "leading_lines", "pov", "film"),
        "partial": ("over_shoulder", "closeup", "framed", "reflection"),
        "candid": ("motion_blur", "low_angle", "wide", "flash"),
        "group": ("wide", "rule_of_thirds", "framed"),
        "portrait": ("closeup", "rule_of_thirds", "backlit"),
    }
    return rng.choice(pools.get(composition, pools["scene"]))


def choose_expression(
    scene: str,
    requested: str = "auto",
    *,
    composition: str = "scene",
    rng: random.Random | None = None,
) -> str:
    """选一个表情；auto 按场景关键词推断。"""
    rng = rng or random
    value = str(requested or "auto").strip().lower()
    if value in EXPRESSION_PROMPTS:
        return value
    text = str(scene or "")
    if any(word in text for word in ("困", "睡", "哈欠", "早起")):
        return "sleepy"
    elif any(word in text for word in ("画", "书", "论文", "作业", "考试")):
        return rng.choice(("focused", "thinking"))
    elif any(word in text for word in ("跑", "下课", "冲", "跳")):
        return "laughing"
    elif any(word in text for word in ("夸", "表扬", "好看")):
        return rng.choice(("shy", "proud"))
    elif any(word in text for word in ("雨", "阴天")):
        return "soft"
    elif composition == "group":
        return rng.choice(("laughing", "smile"))
    return "smile"


def character_anchors(spec: dict, wardrobe: dict | None = None) -> str:
    """固定身份锚点；只在人物出镜时拼进提示词。"""
    hair = str(spec.get("hair") or "silver-white bob hair with pale ice-blue gradient tips")
    eyes = str(spec.get("eyes") or "both eyes glacier-blue with small star-shaped highlights")
    outfit = str((wardrobe or {}).get("outfit") or spec.get("outfit") or "")
    shoes = str((wardrobe or {}).get("shoes") or "")
    socks = str((wardrobe or {}).get("socks") or "")
    bits = [
        hair,
        eyes,
        "silver four-pointed star hairpin",
        "black choker with a tiny star pendant",
    ]
    if outfit:
        bits.append(outfit)
    if socks:
        bits.append(socks)
    if shoes:
        bits.append(shoes)
    return ", ".join(bit.strip(" ,") for bit in bits if bit.strip())


def composition_prompt(composition: str, scene: str, allow_other_people: bool = True) -> str:
    scene_text = str(scene or "").strip()
    if composition == "scene":
        return (
            "first-person POV lifestyle snapshot, the character is NOT in frame, "
            f"focus on {scene_text or 'everyday objects'}, everyday details, off-center candid framing, "
            "shallow depth of field, natural light, lived-in atmosphere"
        )
    if composition == "partial":
        return (
            "the character only partially appears: hands, back view, side profile, shoulder, or at the frame edge, "
            "face mostly out of frame or turned away, not centered, candid snapshot, "
            f"scene: {scene_text or 'daily life moment'}, natural composition, shallow depth of field"
        )
    if composition == "candid":
        return (
            "candid motion snapshot, slight motion blur, character moving through or running out of the frame, "
            "off-center composition, slight camera shake, imperfect framing, natural candid moment, "
            f"scene: {scene_text or 'campus life'}"
        )
    if composition == "group":
        people = (
            "other people appear in the background as soft blurred figures, faces not detailed, "
            "the character is not centered"
            if allow_other_people
            else "no other people, the character is not centered"
        )
        return (
            f"candid group-life snapshot, {people}, "
            f"scene: {scene_text or 'a small gathering'}, natural framing, shallow depth of field"
        )
    return (
        "character portrait, upper body, centered composition, looking at the viewer, "
        f"scene: {scene_text or 'quiet daily moment'}, clean background"
    )


def build_prompt(
    scene: str,
    *,
    composition: str,
    spec: dict,
    allow_other_people: bool = True,
    include_character: bool | None = None,
    style: str = "",
    shot: str = "auto",
    expression: str = "auto",
    outfit: str = "auto",
) -> str:
    """拼装给 Seedream 的最终提示词。"""
    composition = composition if composition in COMPOSITIONS else "scene"
    if include_character is None:
        include_character = composition != "scene"
    base_style = style or (
        "anime illustration, soft cel shading, clean lineart, light watercolor texture, "
        "low saturation cool palette, natural light, no text, no watermark"
    )
    chosen_shot = choose_shot(scene, shot, composition=composition)
    chosen_expression = choose_expression(scene, expression, composition=composition)
    parts = [
        composition_prompt(composition, scene, allow_other_people),
        SHOT_PRESETS.get(chosen_shot, ""),
        base_style,
    ]
    if include_character:
        wardrobe = wardrobe_for_scene(spec, scene, outfit)
        parts.append("character design: " + character_anchors(spec, wardrobe))
        parts.append("expression: " + EXPRESSION_PROMPTS.get(chosen_expression, "gentle smile"))
        if composition == "group" and allow_other_people:
            parts.append("background people are generic, blurred, no detailed faces, no real-person likeness")
        if composition == "candid":
            parts.append("face may be partially visible, motion blur is intentional, not a clean portrait")
    else:
        parts.append("no character in frame, no face, no self-portrait")
    return ", ".join(part.strip(" ,") for part in parts if part.strip())
