r"""给第三方 qzone 插件加「看空间触发概率」补丁（可重复执行）。

问题：AutoComment 每天 8 点固定读好友说说/评论，没有"今天不刷"的选项。
补丁增加 trigger.comment_chance（0-1），到点先掷骰子，未命中也算一轮任务完成。

用法：
    python scripts/patches/patch_qzone_comment_chance.py "C:\...\plugins\astrbot_plugin_qzone"
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def patch_config(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    if "comment_chance" in text:
        return False
    old = "    comment_cron: str\n    comment_offset: int\n    read_prob: float"
    new = (
        "    comment_cron: str\n    comment_offset: int\n"
        "    comment_chance: float\n    read_prob: float"
    )
    if old not in text:
        return False
    path.write_text(text.replace(old, new), encoding="utf-8", newline="\n")
    return True


def patch_scheduler(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    if "今天不刷空间" in text:
        return False
    old = '''    async def do_task(self):
        posts = await self.service.query_feeds(
            pos=0,
            num=20,
            no_self=True,
            no_commented=True,
        )'''
    new = '''    async def do_task(self):
        chance = float(getattr(self.cfg.trigger, "comment_chance", 0.5) or 0.5)
        if random.random() >= chance:
            logger.info(f"[{self.job_name}] 今天不刷空间（随机跳过，概率 {chance:.0%}）")
            return
        posts = await self.service.query_feeds(
            pos=0,
            num=20,
            no_self=True,
            no_commented=True,
        )'''
    if old not in text:
        return False
    path.write_text(text.replace(old, new), encoding="utf-8", newline="\n")
    return True


def patch_schema(path: Path) -> bool:
    if not path.is_file():
        return False
    data = json.loads(path.read_text(encoding="utf-8"))
    trigger = data.get("trigger")
    if not isinstance(trigger, dict) or "comment_chance" in trigger:
        return False
    trigger["comment_chance"] = {
        "description": "看空间触发概率",
        "type": "float",
        "default": 0.5,
        "hint": "0-1；每天早上随机窗口内按此概率决定今天要不要刷空间/评论",
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: patch_qzone_comment_chance.py <qzone 插件目录>")
        return 2
    root = Path(sys.argv[1])
    if not (root / "core" / "scheduler.py").is_file():
        print(f"找不到 qzone 插件文件：{root}")
        return 1
    print("config.py:", "patched" if patch_config(root / "core" / "config.py") else "already/未匹配")
    print("scheduler.py:", "patched" if patch_scheduler(root / "core" / "scheduler.py") else "already/未匹配")
    print("schema:", "patched" if patch_schema(root / "_conf_schema.json") else "already/未匹配")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
