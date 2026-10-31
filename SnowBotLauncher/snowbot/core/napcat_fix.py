"""NapCat 插件商店镜像修复。

NapCat 的插件索引只在硬编码的 raw 镜像列表里尝试；GitHub 不可达时全部失败。
这里把可用的 gh-proxy.org 镜像注入 napcat.mjs 的列表首位，并在修改前备份。
"""

from __future__ import annotations

import re
import shutil
import time
from pathlib import Path

MIRROR = "https://gh-proxy.org/https://raw.githubusercontent.com"


def patch_napcat_mirror(napcat_dir: str) -> tuple[bool, str]:
    if not napcat_dir:
        return False, "NapCat 目录未配置。"
    path = Path(napcat_dir) / "napcat.mjs"
    if not path.exists():
        return False, f"找不到 {path}"

    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        return False, f"读取 napcat.mjs 失败：{exc}"

    if MIRROR in text:
        return (
            True,
            "当前 napcat.mjs 已包含可用镜像。\n"
            "如果插件商店仍然报错，请重启 NapCat 后再试。",
        )

    pattern = re.compile(r'l1\s*=\s*\[\s*"https://raw\.githubusercontent\.com",')
    if not pattern.search(text):
        return (
            False,
            "没有找到 NapCat 的镜像列表，版本可能已变化。\n"
            "请更新 SnowBotLauncher 或手动检查 napcat.mjs。",
        )

    backup = path.with_name(
        f"napcat.mjs.bak-snowbot-{time.strftime('%Y%m%d-%H%M%S')}"
    )
    try:
        shutil.copy2(path, backup)
        text = pattern.sub(
            'l1 = [\n  "'
            + MIRROR
            + '",\n  "https://raw.githubusercontent.com",',
            text,
            count=1,
        )
        path.write_text(text, encoding="utf-8")
    except Exception as exc:
        return False, f"修改 napcat.mjs 失败：{exc}"

    return (
        True,
        "已注入 gh-proxy.org 镜像。\n"
        f"备份：{backup.name}\n"
        "请重启 NapCat 后刷新插件商店。",
    )
