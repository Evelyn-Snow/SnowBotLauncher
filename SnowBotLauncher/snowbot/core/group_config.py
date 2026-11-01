"""群聊互动配置的读写辅助。

GCP（astrbot_plugin_group_chat_plus）用 enabled_groups 控制概率引擎的生效
范围：留空 = 所有群启用。启动器用占位群号 "0" 表示"全部停用"，这样一个
复选框加上群号列表就能表达 关闭 / 指定群 / 所有群 三种状态。
"""

from __future__ import annotations

import re

DISABLE_ALL = ["0"]
_SPLIT = re.compile(r"[\s,，、;；]+")


def parse_group_ids(text: str) -> list[str]:
    """把逗号/空格分隔的群号输入清洗成去重列表，只保留纯数字群号。"""
    ids: list[str] = []
    seen: set[str] = set()
    for token in _SPLIT.split(str(text or "")):
        token = token.strip()
        if token and token.isdigit() and token not in seen:
            seen.add(token)
            ids.append(token)
    return ids


def build_scoped_groups(enabled: bool, ids: list[str]) -> list[str]:
    """根据开关和群号列表生成 enabled_groups / poke_enabled_groups。

    关闭时写入占位群号，使任何真实群都不匹配；开启时写入清洗后的列表，
    留空表示所有群启用（与 GCP 原生语义一致）。
    """
    if not enabled:
        return list(DISABLE_ALL)
    cleaned = [
        item
        for item in dict.fromkeys(str(value).strip() for value in ids)
        if item and item != "0"
    ]
    return cleaned


def is_scope_enabled(groups) -> bool:
    """判断配置里的群号列表是否处于"全部停用"占位状态。"""
    if not isinstance(groups, list):
        return True
    return [str(item) for item in groups] != DISABLE_ALL


def scope_group_text(groups) -> str:
    """把配置里的群号列表还原成输入框文本（去掉占位符）。"""
    if not isinstance(groups, list):
        return ""
    return ", ".join(str(item) for item in groups if str(item) != "0")
