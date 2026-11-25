"""SQLite 存储层：事件账本、事实、洞察、FTS 与向量。

单用户场景，不引入外部数据库。所有写操作在进程内加锁；SQLite 开 WAL。
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_key TEXT UNIQUE NOT NULL,
    ts REAL NOT NULL,
    umo TEXT NOT NULL,
    platform TEXT,
    sender_id TEXT,
    sender_name TEXT,
    role TEXT,
    text TEXT NOT NULL,
    message_id TEXT,
    source TEXT,
    privacy INTEGER DEFAULT 2,
    processed INTEGER DEFAULT 0,
    attempts INTEGER DEFAULT 0,
    meta TEXT,
    created_at REAL
);
CREATE INDEX IF NOT EXISTS idx_events_pending ON events(processed, attempts, id);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);

CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL,
    subject_key TEXT NOT NULL,
    subject_type TEXT,
    predicate TEXT NOT NULL,
    object TEXT NOT NULL,
    object_key TEXT NOT NULL,
    object_type TEXT,
    fact_type TEXT,
    polarity INTEGER DEFAULT 1,
    confidence REAL DEFAULT 0.7,
    importance REAL DEFAULT 0.5,
    privacy INTEGER DEFAULT 2,
    scope TEXT,
    valid_from REAL,
    valid_to REAL,
    learned_at REAL,
    invalidated_at REAL,
    status TEXT DEFAULT 'active',
    supersedes_id INTEGER,
    source_event_ids TEXT,
    evidence TEXT,
    extractor_version TEXT,
    search_text TEXT,
    embedding TEXT,
    meta TEXT,
    created_at REAL
);
CREATE INDEX IF NOT EXISTS idx_facts_sp ON facts(subject_key, predicate, status);
CREATE INDEX IF NOT EXISTS idx_facts_status ON facts(status, importance);
CREATE INDEX IF NOT EXISTS idx_facts_scope ON facts(scope);

CREATE TABLE IF NOT EXISTS insights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope TEXT,
    insight_type TEXT,
    statement TEXT NOT NULL,
    confidence REAL DEFAULT 0.6,
    importance REAL DEFAULT 0.55,
    privacy INTEGER DEFAULT 2,
    evidence_fact_ids TEXT,
    evidence_event_ids TEXT,
    status TEXT DEFAULT 'active',
    supersedes_id INTEGER,
    search_text TEXT,
    embedding TEXT,
    created_at REAL,
    updated_at REAL,
    meta TEXT
);
CREATE INDEX IF NOT EXISTS idx_insights_scope ON insights(scope, status);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
    event_id UNINDEXED, text
);
CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(
    fact_id UNINDEXED, text
);
CREATE VIRTUAL TABLE IF NOT EXISTS insights_fts USING fts5(
    insight_id UNINDEXED, text
);
"""


class MemoryStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self.init_schema()

    # ---------------- 基础 ----------------
    def init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.commit()
                self._conn.close()
            except Exception:
                pass

    @staticmethod
    def _json(value) -> str:
        return json.dumps(value, ensure_ascii=False)

    # ---------------- 事件 ----------------
    def add_event(
        self,
        *,
        event_key: str,
        ts: float,
        umo: str,
        platform: str = "",
        sender_id: str = "",
        sender_name: str = "",
        role: str = "user",
        text: str = "",
        message_id: str = "",
        source: str = "chat",
        privacy: int = 2,
        meta: dict | None = None,
    ) -> bool:
        if not str(text or "").strip():
            return False
        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT OR IGNORE INTO events
                (event_key, ts, umo, platform, sender_id, sender_name, role,
                 text, message_id, source, privacy, processed, attempts, meta, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,0,0,?,?)
                """,
                (
                    event_key,
                    float(ts),
                    umo,
                    platform,
                    sender_id,
                    sender_name,
                    role,
                    str(text).strip(),
                    message_id,
                    source,
                    int(privacy),
                    self._json(meta or {}),
                    time.time(),
                ),
            )
            inserted = cursor.rowcount > 0
            if inserted:
                self._conn.execute(
                    "INSERT INTO events_fts(event_id, text) VALUES (?, ?)",
                    (cursor.lastrowid, str(text).strip()),
                )
            self._conn.commit()
            return inserted

    def pending_events(self, limit: int = 24) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM events
                WHERE processed = 0 AND attempts < 3
                ORDER BY id ASC LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def bump_attempts(self, ids: list[int]) -> None:
        if not ids:
            return
        with self._lock:
            marks = ",".join("?" for _ in ids)
            self._conn.execute(
                f"UPDATE events SET attempts = attempts + 1 WHERE id IN ({marks})",
                list(ids),
            )
            self._conn.execute(
                f"UPDATE events SET processed = 2 WHERE id IN ({marks}) AND attempts >= 3",
                list(ids),
            )
            self._conn.commit()

    def mark_processed(self, ids: list[int], status: int = 1) -> None:
        if not ids:
            return
        with self._lock:
            marks = ",".join("?" for _ in ids)
            self._conn.execute(
                f"UPDATE events SET processed = ? WHERE id IN ({marks})",
                [int(status), *ids],
            )
            self._conn.commit()

    def event_count(self, processed: int | None = None) -> int:
        with self._lock:
            if processed is None:
                row = self._conn.execute("SELECT COUNT(*) FROM events").fetchone()
            else:
                row = self._conn.execute(
                    "SELECT COUNT(*) FROM events WHERE processed = ?", (int(processed),)
                ).fetchone()
        return int(row[0] or 0)

    # ---------------- 事实 ----------------
    def add_fact(self, fact: dict) -> int:
        now = time.time()
        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT INTO facts
                (subject, subject_key, subject_type, predicate, object, object_key,
                 object_type, fact_type, polarity, confidence, importance, privacy,
                 scope, valid_from, valid_to, learned_at, invalidated_at, status,
                 supersedes_id, source_event_ids, evidence, extractor_version,
                 search_text, embedding, meta, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    fact.get("subject"),
                    fact.get("subject_key"),
                    fact.get("subject_type"),
                    fact.get("predicate"),
                    fact.get("object"),
                    fact.get("object_key"),
                    fact.get("object_type"),
                    fact.get("fact_type"),
                    int(fact.get("polarity") or 1),
                    float(fact.get("confidence") or 0.7),
                    float(fact.get("importance") or 0.5),
                    int(fact.get("privacy") or 2),
                    fact.get("scope") or "",
                    fact.get("valid_from"),
                    None,
                    float(fact.get("learned_at") or now),
                    None,
                    "active",
                    fact.get("supersedes_id"),
                    self._json(fact.get("source_event_ids") or []),
                    fact.get("evidence") or "",
                    fact.get("extractor_version") or "v1",
                    fact.get("search_text") or "",
                    self._json(fact.get("embedding")) if fact.get("embedding") else None,
                    self._json(fact.get("meta") or {}),
                    now,
                ),
            )
            fact_id = int(cursor.lastrowid)
            self._conn.execute(
                "INSERT INTO facts_fts(fact_id, text) VALUES (?, ?)",
                (fact_id, fact.get("search_text") or ""),
            )
            self._conn.commit()
            return fact_id

    def find_active(self, subject_key: str, predicate: str, now: float | None = None) -> list[dict]:
        now = float(now if now is not None else time.time())
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM facts
                WHERE subject_key = ? AND predicate = ? AND status = 'active'
                  AND (valid_to IS NULL OR valid_to > ?)
                ORDER BY id DESC LIMIT 20
                """,
                (subject_key, predicate, now),
            ).fetchall()
        return [dict(row) for row in rows]

    def supersede_fact(
        self, old_id: int, new_id: int, *, valid_to: float, now: float | None = None
    ) -> None:
        now = float(now if now is not None else time.time())
        with self._lock:
            self._conn.execute(
                """
                UPDATE facts
                SET status = 'superseded', valid_to = ?, invalidated_at = ?
                WHERE id = ? AND status = 'active'
                """,
                (float(valid_to), now, int(old_id)),
            )
            self._conn.execute(
                "UPDATE facts SET supersedes_id = ? WHERE id = ?",
                (int(old_id), int(new_id)),
            )
            self._conn.commit()

    def add_fact_source(self, fact_id: int, event_id: int) -> None:
        with self._lock:
            row = self._conn.execute(
                "SELECT source_event_ids FROM facts WHERE id = ?", (int(fact_id),)
            ).fetchone()
            if not row:
                return
            try:
                ids = json.loads(row[0] or "[]")
            except Exception:
                ids = []
            if event_id not in ids:
                ids.append(int(event_id))
                self._conn.execute(
                    "UPDATE facts SET source_event_ids = ? WHERE id = ?",
                    (self._json(ids), int(fact_id)),
                )
                self._conn.commit()

    def active_facts(self, limit: int = 1200) -> list[dict]:
        now = time.time()
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM facts
                WHERE status = 'active' AND (valid_to IS NULL OR valid_to > ?)
                ORDER BY importance DESC, valid_from DESC LIMIT ?
                """,
                (now, max(1, int(limit))),
            ).fetchall()
        return [dict(row) for row in rows]

    def set_fact_embedding(self, fact_id: int, vector: list[float] | None) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE facts SET embedding = ? WHERE id = ?",
                (self._json(vector) if vector else None, int(fact_id)),
            )
            self._conn.commit()

    # ---------------- 洞察 ----------------
    def add_insight(self, insight: dict) -> int:
        now = time.time()
        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT INTO insights
                (scope, insight_type, statement, confidence, importance, privacy,
                 evidence_fact_ids, evidence_event_ids, status, supersedes_id,
                 search_text, embedding, created_at, updated_at, meta)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    insight.get("scope") or "",
                    insight.get("insight_type") or "pattern",
                    insight.get("statement"),
                    float(insight.get("confidence") or 0.6),
                    float(insight.get("importance") or 0.55),
                    int(insight.get("privacy") or 2),
                    self._json(insight.get("evidence_fact_ids") or []),
                    self._json(insight.get("evidence_event_ids") or []),
                    "active",
                    insight.get("supersedes_id"),
                    insight.get("search_text") or insight.get("statement") or "",
                    self._json(insight.get("embedding")) if insight.get("embedding") else None,
                    now,
                    now,
                    self._json(insight.get("meta") or {}),
                ),
            )
            insight_id = int(cursor.lastrowid)
            self._conn.execute(
                "INSERT INTO insights_fts(insight_id, text) VALUES (?, ?)",
                (insight_id, insight.get("search_text") or insight.get("statement") or ""),
            )
            self._conn.commit()
            return insight_id

    def active_insights(self, limit: int = 400) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM insights WHERE status = 'active'
                ORDER BY importance DESC, updated_at DESC LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def supersede_insight(self, old_id: int, new_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE insights SET status = 'superseded', updated_at = ? WHERE id = ?",
                (time.time(), int(old_id)),
            )
            self._conn.execute(
                "UPDATE insights SET supersedes_id = ? WHERE id = ?",
                (int(old_id), int(new_id)),
            )
            self._conn.commit()

    def set_insight_embedding(self, insight_id: int, vector: list[float] | None) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE insights SET embedding = ? WHERE id = ?",
                (self._json(vector) if vector else None, int(insight_id)),
            )
            self._conn.commit()

    # ---------------- meta / stats ----------------
    def get_meta(self, key: str, default=None):
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM meta WHERE key = ?", (str(key),)
            ).fetchone()
        if not row:
            return default
        try:
            return json.loads(row[0])
        except Exception:
            return row[0]

    def set_meta(self, key: str, value) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                (str(key), self._json(value)),
            )
            self._conn.commit()

    def stats(self) -> dict:
        with self._lock:
            def one(sql: str) -> int:
                row = self._conn.execute(sql).fetchone()
                return int(row[0] or 0)

            return {
                "events": one("SELECT COUNT(*) FROM events"),
                "pending_events": one(
                    "SELECT COUNT(*) FROM events WHERE processed = 0 AND attempts < 3"
                ),
                "facts": one("SELECT COUNT(*) FROM facts"),
                "active_facts": one(
                    "SELECT COUNT(*) FROM facts WHERE status = 'active'"
                ),
                "insights": one("SELECT COUNT(*) FROM insights"),
                "active_insights": one(
                    "SELECT COUNT(*) FROM insights WHERE status = 'active'"
                ),
            }
