"""把 LivingMemory 的历史摘要/原子导入 snow_memory 的事件账本。

AstrBot 的 conversations 表只保留最近几十条，11-20 那批感冒对话已经轮转掉了；
LivingMemory 的 documents/atoms 还留着摘要，可以作为补充证据。

用法：
  python scripts/memory_bootstrap_livingmemory.py \
    --livingmemory ".../plugin_data/astrbot_plugin_livingmemory/livingmemory.db" \
    --memory ".../plugin_data/astrbot_plugin_snow_memory/memory.db"
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

# 已知的读书幻觉：上游摘要里反复出现，但没有真实阅读事件支撑。
_BAD_BOOK_RE = re.compile(r"西游记|西遊記|五行山|水帘洞|石猴")


def _ts(value, fallback=None):
    if isinstance(value, (int, float)) and value:
        return float(value)
    text = str(value or "").strip()
    if not text:
        return float(fallback or 0)
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text[: len(fmt) + 6], fmt).timestamp()
        except ValueError:
            continue
    try:
        return float(text)
    except ValueError:
        return float(fallback or 0)


def _privacy(umo: str) -> int:
    return 3 if ":GroupMessage:" in str(umo) else 4


def import_documents(conn, store: MemoryStore, dry_run=False) -> dict:
    stats = {"documents": 0, "inserted": 0, "skipped": 0}
    rows = conn.execute("SELECT id, text, metadata, created_at FROM documents").fetchall()
    for row in rows:
        stats["documents"] += 1
        try:
            meta = json.loads(row["metadata"] or "{}")
        except Exception:
            meta = {}
        text = str(meta.get("canonical_summary") or meta.get("persona_summary") or row["text"] or "").strip()
        facts = meta.get("key_facts") or []
        if isinstance(facts, list) and facts:
            extra = "；".join(str(item) for item in facts if item)
            if extra and extra not in text:
                text = f"{text}\n{extra}"
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            stats["skipped"] += 1
            continue
        if _BAD_BOOK_RE.search(text):
            stats["skipped"] += 1
            continue
        umo = str(meta.get("session_id") or "legacy:unknown")
        ts = _ts(
            meta.get("source_time_start"),
            _ts(meta.get("create_time"), _ts(row["created_at"], 0)),
        )
        key = f"lm_doc:{row['id']}:{sha1_text(text)}"
        if dry_run:
            stats["inserted"] += 1
            continue
        if store.add_event(
            event_key=key,
            ts=ts,
            umo=umo,
            platform="legacy",
            sender_id="",
            sender_name="回忆",
            role="memory",
            text=text[:1800],
            source="legacy_livingmemory",
            privacy=_privacy(umo),
            meta={"topics": meta.get("topics") or [], "legacy": True},
        ):
            stats["inserted"] += 1
        else:
            stats["skipped"] += 1
    return stats


def import_atoms(conn, store: MemoryStore, dry_run=False) -> dict:
    stats = {"atoms": 0, "inserted": 0, "skipped": 0}
    rows = conn.execute(
        "SELECT id, content, created_at, session_id FROM memory_atoms WHERE status='active'"
    ).fetchall()
    for row in rows:
        stats["atoms"] += 1
        text = str(row["content"] or "").strip()
        if not text or _BAD_BOOK_RE.search(text):
            stats["skipped"] += 1
            continue
        umo = str(row["session_id"] or "legacy:unknown")
        key = f"lm_atom:{row['id']}:{sha1_text(text)}"
        if dry_run:
            stats["inserted"] += 1
            continue
        if store.add_event(
            event_key=key,
            ts=_ts(row["created_at"], 0),
            umo=umo,
            platform="legacy",
            sender_id="",
            sender_name="回忆",
            role="memory_atom",
            text=text[:800],
            source="legacy_atom",
            privacy=_privacy(umo),
            meta={"legacy": True},
        ):
            stats["inserted"] += 1
        else:
            stats["skipped"] += 1
    return stats


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--livingmemory", required=True)
    parser.add_argument("--memory", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    lm_path = Path(args.livingmemory)
    if not lm_path.exists():
        print(f"LivingMemory 数据库不存在：{lm_path}")
        return 1
    conn = sqlite3.connect(str(lm_path))
    conn.row_factory = sqlite3.Row
    store = MemoryStore(Path(args.memory))
    doc_stats = import_documents(conn, store, args.dry_run)
    atom_stats = import_atoms(conn, store, args.dry_run)
    conn.close()
    print(json.dumps({"documents": doc_stats, "atoms": atom_stats}, ensure_ascii=False, indent=2))
    print(json.dumps(store.stats(), ensure_ascii=False, indent=2))
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
