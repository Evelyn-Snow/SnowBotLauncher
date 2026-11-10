"""状态/签名更新的纯逻辑（不依赖 AstrBot，可单测）。"""

from __future__ import annotations

import re

STATUS_BY_STATE = {
    "sleep": "睡觉中",
    "focus": "学习中",
    "busy": "忙碌",
    "social": "在线",
    "available": "在线",
    "transit": "出去浪",
}

STATUS_BY_KEYWORD = (
    ("论文", "肝作业"),
    ("作业", "肝作业"),
    ("自习", "学习中"),
    ("图书馆", "学习中"),
    ("上课", "学习中"),
    ("英语", "学习中"),
    ("运动", "元气满满"),
    ("跑步", "元气满满"),
    ("睡", "睡觉中"),
    ("午休", "睡觉中"),
    ("追剧", "追剧中"),
    ("看剧", "追剧中"),
    ("听歌", "听歌中"),
    ("游戏", "timi中"),
    ("摸鱼", "摸鱼中"),
    ("散步", "悠哉哉"),
    ("泡茶", "悠哉哉"),
    ("发呆", "想静静"),
    ("聊天", "在线"),
)

FALLBACK_SIGNATURES = (
    "今天也在认真生活",
    "慢慢来，比较快",
    "把日子过成自己喜欢的样子",
    "有点忙，但还好",
    "风很轻，事情一件件做",
)


def clean_signature(raw: str, max_chars: int = 24) -> str:
    """把模型输出收成一句签名：去引号/换行/标签，截断。"""
    text = str(raw or "").strip()
    text = re.sub(r"^[\"'“”‘’#*\s]+|[\"'“”‘’\s]+$", "", text)
    text = re.sub(r"[\r\n]+", " ", text)
    text = re.sub(r"\s{2,}", " ", text)
    text = text.split("。")[0].strip("，,；; ")
    if not text:
        return ""
    limit = max(4, int(max_chars or 24))
    return text[:limit]


def pick_status(activity: str, state: str) -> str:
    """按当前活动和状态选一个 QQ 在线状态名。"""
    text = str(activity or "")
    for keyword, status in STATUS_BY_KEYWORD:
        if keyword in text:
            return status
    return STATUS_BY_STATE.get(str(state or "").lower(), "在线")


def build_signature_prompt(activity: str, place: str, state: str, hour: int) -> str:
    scene = f"现在{activity}" if activity else "现在没什么特别的事"
    if place:
        scene += f"，在{place}"
    period = "早上" if hour < 9 else "上午" if hour < 12 else "中午" if hour < 14 else "下午" if hour < 18 else "晚上"
    return (
        f"你是小雪，一个大学生。现在是{period}，{scene}（状态：{state or '日常'}）。\n"
        "写一句你此刻想挂在 QQ 签名上的短句：不超过 20 个汉字，第一人称，口语、自然、"
        "有一点自己的小情绪或画面感；不要引号、不要解释、不要带话题标签。只输出这一句。"
    )


def fallback_signature(index: int = 0) -> str:
    return FALLBACK_SIGNATURES[int(index) % len(FALLBACK_SIGNATURES)]
