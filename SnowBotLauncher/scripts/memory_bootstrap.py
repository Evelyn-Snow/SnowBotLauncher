"""把 AstrBot 的历史对话导入 snow_memory 的事件账本（一次性 bootstrap）。

用法：
  python scripts/memory_bootstrap.py \
    --db "C:\\...\\core\\data\\data_v4.db" \
    --memory "C:\\...\\plugin_data\\astrbot_plugin_snow_memory\\memory.db" \
    --owner-qq 1282164886

只导入原始对话，不导入画像/卡片/摘要——那些是二次加工产物，容易把幻觉带进来。
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from plugins.astrbot_plugin_snow_memory.library import sha1_text  # noqa: E402
from plugins.astrbot_plugin_snow_memory.store import MemoryStore  # noqa: E402

_REMINDER_RE = re.compile(r"<system_reminder>.*?</system_reminder>", re.S)
_IMAGE_PATH_RE = re.compile(r"\[Image \d+:[^\]]*\]")
_AT_RE = re.compile(r"\[At:[^\]]+\]")
_COMPONENT_RE = re.compile(r"\[ComponentType\.[^\]]+\]")
_GROUP_PREFIX_RE = re.compile(
    r"^\[(?P<ts>[^\]]+)\]\s*(?P<name>.+?)\(ID:(?P<id>\d+)\)"
    r"(?:\[戳一戳事件\][^:]*)?:\s*(?P<text>.*)$",
    re.S,
)
_DATETIME_RE = re.compile(r"Current datetime:\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2})")
_SYSTEM_TASK_RE = re.compile(r"^\s*\[系统任务")


def clean_text(text: str) -> str:
    value = _REMINDER_RE.sub("", str(text or ""))
    value = _IMAGE_PATH_RE.sub("[图片]", value)
    value = _AT_RE.sub("", value)
    value = _COMPONENT_RE.sub("", value)
    value = re.sub(r"&&[^&\r\n]{1,40}&&", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def parse_stamp(text: str, fallback: float) -> float:
    match = _DATETIME_RE.search(str(text or ""))
    if match:
        try:
            return datetime.strptime(match.group(1), "%Y-%m-%d %H:%M").timestamp()
        except ValueError:
            pass
    return fallback


def profile_names(profile_dir: Path) -> dict[str, str]:
    names: dict[str, str] = {}
    if not profile_dir.is_dir():
        return names
    for path in profile_dir.glob("*.md"):
        try:
            text = path.read_text(encoding="utf-8-sig")
        except Exception:
            continue
        match = re.search(r"^昵称:\s*(.+)$", text, re.M)
        if match:
            names[path.stem] = match.group(1).strip()
    return names


def import_conversations(
    db_path: Path,
    store: MemoryStore,
    *,
    owner_qq: str,
    names: dict[str, str],
    dry_run: bool = False,
    include_webchat: bool = False,
) -> dict:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT platform_id, user_id, content, updated_at FROM conversations"
    ).fetchall()
    stats = {"conversations": 0, "messages": 0, "inserted": 0, "skipped": 0}
    for row in rows:
        umo = str(row["user_id"] or "")
        platform = str(row["platform_id"] or "")
        if platform == "webchat" and not include_webchat:
            stats["skipped"] += 1
            continue
        try:
            messages = json.loads(row["content"] or "[]")
        except Exception:
            continue
        if not isinstance(messages, list):
            continue
        try:
            fallback_ts = datetime.strptime(
                str(row["updated_at"])[:19], "%Y-%m-%d %H:%M:%S"
            ).timestamp()
        except Exception:
            fallback_ts = 0.0
        is_group = ":GroupMessage:" in umo
        stats["conversations"] += 1
        last_user_ts = fallback_ts
        for index, message in enumerate(messages):
            if not isinstance(message, dict):
                continue
            role = str(message.get("role") or "")
            if role not in ("user", "assistant"):
                continue
            parts = message.get("content")
            if isinstance(parts, list):
                raw = "".join(
                    str(part.get("text") or "")
                    for part in parts
                    if isinstance(part, dict)
                )
            else:
                raw = str(parts or "")
            text = clean_text(raw)
            if not text or "戳一戳事件" in text or _SYSTEM_TASK_RE.search(text):
                stats["skipped"] += 1
                continue
            if re.fullmatch(r"(?:\[图片\]\s*)+", text):
                stats["skipped"] += 1
                continue
            ts = last_user_ts or fallback_ts
            sender_id = ""
            sender_name = ""
            if role == "user":
                if is_group:
                    match = _GROUP_PREFIX_RE.match(text)
                    if match:
                        sender_name = match.group("name").strip()
                        sender_id = match.group("id")
                        text = clean_text(match.group("text"))
                        try:
                            stamp_match = re.match(
                                r"(\d{4}-\d{2}-\d{2})\s+\S+\s+(\d{2}:\d{2}:\d{2})",
                                match.group("ts"),
                            )
                            if stamp_match:
                                ts = datetime.strptime(
                                    f"{stamp_match.group(1)} {stamp_match.group(2)}",
                                    "%Y-%m-%d %H:%M:%S",
                                ).timestamp()
                            else:
                                ts = parse_stamp(raw, fallback_ts)
                        except Exception:
                            ts = parse_stamp(raw, fallback_ts)
                    else:
                        stats["skipped"] += 1
                        continue
                else:
                    sender_id = umo.rsplit(":", 1)[-1]
                    sender_name = names.get(sender_id) or (
                        "哥哥" if sender_id == owner_qq else f"QQ{sender_id}"
                    )
                    ts = parse_stamp(raw, fallback_ts)
                last_user_ts = ts
            else:
                sender_id = "3651873041"
                sender_name = "小雪"
            if not text:
                stats["skipped"] += 1
                continue
            stats["messages"] += 1
            key = f"legacy:{umo}:{index}:{role}:{sha1_text(text)}"
            if dry_run:
                stats["inserted"] += 1
                continue
            if store.add_event(
                event_key=key,
                ts=float(ts or fallback_ts),
                umo=umo,
                platform=platform,
                sender_id=sender_id,
                sender_name=sender_name,
                role=role,
                text=text[:1600],
                message_id="",
                source="legacy_chat",
                privacy=3 if is_group else 4,
                meta={"group": is_group, "legacy": True},
            ):
                stats["inserted"] += 1
            else:
                stats["skipped"] += 1
    conn.close()
    return stats


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True, help="AstrBot data_v4.db 路径")
    parser.add_argument("--memory", required=True, help="snow_memory memory.db 路径")
    parser.add_argument("--owner-qq", default="1282164886")
    parser.add_argument(
        "--profile-dir",
        default=r"C:\Evelyn_Snow\画像",
        help="画像目录，用来取昵称",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--include-webchat",
        action="store_true",
        help="连网页测试台的对话也导入（默认不导入，避免测试内容污染记忆）",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    memory_path = Path(args.memory)
    if not db_path.exists():
        print(f"数据库不存在：{db_path}")
        return 1
    names = profile_names(Path(args.profile_dir))
    store = MemoryStore(memory_path)
    stats = import_conversations(
        db_path,
        store,
        owner_qq=str(args.owner_qq),
        names=names,
        dry_run=args.dry_run,
        include_webchat=args.include_webchat,
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    print(json.dumps(store.stats(), ensure_ascii=False, indent=2))
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
