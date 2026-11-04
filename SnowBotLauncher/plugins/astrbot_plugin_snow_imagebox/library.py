"""图库的本地存储、检索与清理。

图库是一个普通目录：`<library_path>/images/` 放图片，`index.json` 放元数据。
不依赖 AstrBot，方便单独测试；插件层只负责从聊天事件取图、发送和工具封装。
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import threading
import time
from pathlib import Path
from typing import Any

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
GENERIC_DESCRIPTION = "聊天图片"
DEFAULT_TAGS = ["未分类"]
_TAG_SPLIT = re.compile(r"[\s,，、;；/|]+")
_TERM_SPLIT = re.compile(r"[\s,，、;；/|]+")


def _now() -> float:
    return time.time()


def _clean_text(value: Any, limit: int = 500) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def normalize_tags(raw: Any) -> list[str]:
    """把逗号/空格分隔的标签整理成去重列表。"""
    if isinstance(raw, (list, tuple, set)):
        parts = [str(item) for item in raw]
    else:
        parts = _TAG_SPLIT.split(str(raw or ""))
    tags: list[str] = []
    seen: set[str] = set()
    for part in parts:
        tag = _clean_text(part, 24).strip("#")
        key = tag.lower()
        if tag and key not in seen:
            seen.add(key)
            tags.append(tag)
        if len(tags) >= 8:
            break
    return tags or list(DEFAULT_TAGS)


def detect_extension(data: bytes, fallback: str = "") -> str:
    """根据文件头判断图片扩展名，避免把 GIF/WebP 存成 jpg。"""
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data.startswith(b"BM"):
        return ".bmp"
    suffix = str(fallback or "").lower()
    if suffix in IMAGE_EXTS:
        return ".jpg" if suffix == ".jpeg" else suffix
    return ".jpg"


# 自发收藏被权限/频率规则挡下时返回给模型的话：不含“拒绝对方”的指令，
# 并明确要求不要复读工具调用前已经发出的内容（否则对方会看到两条一样的消息）。
AUTO_SAVE_SKIPPED = (
    "这张图这次没有收藏。不要向对方解释原因，也不要重复你已经说过的话，"
    "直接基于这个结果继续正常回复。"
)


class ImageLibrary:
    """线程安全的本地图片图库。"""

    def __init__(
        self,
        root: str | Path,
        *,
        max_items: int = 300,
        retention_days: int = 180,
        min_uses: int = 2,
        max_file_mb: int = 8,
        max_total_mb: int = 500,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.images_dir = self.root / "images"
        self.index_path = self.root / "index.json"
        self.log_path = self.root / "cleanup.log"
        self.max_items = max(10, int(max_items))
        self.retention_days = max(1, int(retention_days))
        self.min_uses = max(0, int(min_uses))
        self.max_file_bytes = max(1, int(max_file_mb)) * 1024 * 1024
        self.max_total_bytes = max(1, int(max_total_mb)) * 1024 * 1024
        self._lock = threading.RLock()
        self._data: dict[str, Any] = {"version": 1, "items": [], "last_cleanup": 0}
        self.load()

    # ---------------- 基础 ----------------
    def _ensure_dirs(self) -> None:
        self.images_dir.mkdir(parents=True, exist_ok=True)

    def load(self) -> None:
        self._ensure_dirs()
        data: dict[str, Any] = {}
        try:
            if self.index_path.is_file():
                data = json.loads(self.index_path.read_text(encoding="utf-8-sig"))
        except Exception:
            data = {}
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, list):
            items = []
        cleaned: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            image_id = str(item.get("id") or "").strip()
            filename = str(item.get("file") or "").strip()
            if not image_id or not filename:
                continue
            cleaned.append(item)
        self._data = {
            "version": 1,
            "items": cleaned,
            "last_cleanup": float(data.get("last_cleanup") or 0)
            if isinstance(data, dict)
            else 0,
        }

    def save(self) -> None:
        self._ensure_dirs()
        payload = json.dumps(self._data, ensure_ascii=False, indent=2)
        tmp = self.index_path.with_name(
            f"{self.index_path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, self.index_path)

    def items(self) -> list[dict[str, Any]]:
        with self._lock_guard():
            return [dict(item) for item in self._data["items"]]

    def get(self, image_id: str) -> dict[str, Any] | None:
        wanted = str(image_id or "").strip()
        if not wanted:
            return None
        with self._lock_guard():
            for item in self._data["items"]:
                if str(item.get("id")) == wanted:
                    return item
            return None

    def file_path(self, item: dict[str, Any]) -> Path:
        return (self.root / str(item.get("file") or "")).resolve()

    def _public(self, item: dict[str, Any], score: float = 0) -> dict[str, Any]:
        created = float(item.get("created_at") or 0)
        last_used = float(item.get("last_used_at") or 0)
        return {
            "id": item.get("id"),
            "description": item.get("description") or GENERIC_DESCRIPTION,
            "tags": list(item.get("tags") or []),
            "use_count": int(item.get("use_count") or 0),
            "created_at": created,
            "last_used_at": last_used,
            "size": int(item.get("size") or 0),
            **({"score": round(score, 1)} if score else {}),
        }

    # ---------------- 保存 ----------------
    def add_bytes(
        self,
        data: bytes,
        description: str = "",
        tags: Any = None,
        *,
        source: str = "chat",
        fallback_ext: str = "",
    ) -> tuple[dict[str, Any], str]:
        if not data:
            raise ValueError("图片内容为空")
        if len(data) > self.max_file_bytes:
            raise ValueError(
                f"图片太大（{len(data) / 1024 / 1024:.1f} MB），"
                f"上限 {self.max_file_bytes / 1024 / 1024:.0f} MB"
            )
        desc = _clean_text(description, 500) or GENERIC_DESCRIPTION
        tag_list = normalize_tags(tags)
        sha = hashlib.sha256(data).hexdigest()
        image_id = sha[:10]
        with self._lock_guard():
            existing = next(
                (
                    item
                    for item in self._data["items"]
                    if str(item.get("sha256")) == sha
                ),
                None,
            )
            if existing:
                merged_tags = normalize_tags(
                    list(existing.get("tags") or []) + tag_list
                )
                existing["tags"] = merged_tags
                if desc and desc != GENERIC_DESCRIPTION:
                    existing["description"] = desc
                existing["updated_at"] = _now()
                self.save()
                return dict(existing), "duplicate"

            ext = detect_extension(data, fallback_ext)
            dest = self.images_dir / f"{image_id}{ext}"
            dest.write_bytes(data)
            now = _now()
            item = {
                "id": image_id,
                "file": str(dest.relative_to(self.root)).replace("\\", "/"),
                "sha256": sha,
                "description": desc,
                "tags": tag_list,
                "created_at": now,
                "updated_at": now,
                "last_used_at": 0.0,
                "use_count": 0,
                "favorite": False,
                "size": len(data),
                "source": source,
            }
            self._data["items"].append(item)
            removed = self._enforce_limits_locked()
            self.save()
            if removed:
                self._append_log(removed, "新增时超出容量上限")
            return dict(item), "saved"

    def add_file(
        self,
        path: str | Path,
        description: str = "",
        tags: Any = None,
        *,
        source: str = "chat",
    ) -> tuple[dict[str, Any], str]:
        src = Path(path)
        if not src.is_file():
            raise ValueError("图片文件不存在")
        size = src.stat().st_size
        if size > self.max_file_bytes:
            raise ValueError(
                f"图片太大（{size / 1024 / 1024:.1f} MB），"
                f"上限 {self.max_file_bytes / 1024 / 1024:.0f} MB"
            )
        return self.add_bytes(
            src.read_bytes(),
            description,
            tags,
            source=source,
            fallback_ext=src.suffix,
        )

    # ---------------- 检索 ----------------
    @staticmethod
    def _terms(query: str) -> list[str]:
        q = _clean_text(query, 120).lower()
        if not q:
            return []
        terms = [part for part in _TERM_SPLIT.split(q) if part]
        if q not in terms:
            terms.append(q)
        return terms

    def search(self, query: str = "", limit: int = 10) -> list[dict[str, Any]]:
        with self._lock_guard():
            return self._search_locked(query, limit)

    def _search_locked(
        self, query: str = "", limit: int = 10
    ) -> list[dict[str, Any]]:
        limit = max(1, min(50, int(limit or 10)))
        terms = self._terms(query)
        scored: list[tuple[float, dict[str, Any]]] = []
        for item in self._data["items"]:
            if not self.file_path(item).is_file():
                continue
            if not terms:
                scored.append((0.0, item))
                continue
            desc = str(item.get("description") or "").lower()
            tags = [str(tag).lower() for tag in (item.get("tags") or [])]
            tag_text = " ".join(tags)
            score = 0.0
            for term in terms:
                if term == str(item.get("id")):
                    score += 30
                if term in tags:
                    score += 8
                elif term and term in tag_text:
                    score += 5
                if term and term in desc:
                    score += 4
            if score > 0:
                scored.append((score, item))
        if terms:
            scored.sort(
                key=lambda pair: (
                    -pair[0],
                    int(pair[1].get("use_count") or 0),
                    float(pair[1].get("last_used_at") or 0),
                )
            )
        else:
            scored.sort(
                key=lambda pair: (
                    int(pair[1].get("use_count") or 0),
                    float(pair[1].get("last_used_at") or 0),
                    float(pair[1].get("created_at") or 0),
                )
            )
        return [self._public(item, score) for score, item in scored[:limit]]

    def pick(self, query: str = "") -> dict[str, Any] | None:
        """在匹配结果里随机挑一张，避免每次都用同一张。"""
        candidates = self.search(query, limit=5)
        if not candidates:
            return None
        full_items = [
            item
            for item in (self.get(candidate.get("id", "")) for candidate in candidates)
            if item is not None
        ]
        if not full_items:
            return None
        weights = [1.0 / (1.0 + int(item.get("use_count") or 0)) for item in full_items]
        return dict(random.choices(full_items, weights=weights, k=1)[0])

    def record_use(self, image_id: str) -> dict[str, Any] | None:
        with self._lock_guard():
            item = self.get(image_id)
            if not item:
                return None
            item["use_count"] = int(item.get("use_count") or 0) + 1
            item["last_used_at"] = _now()
            self.save()
            return dict(item)

    def delete(self, image_id: str) -> bool:
        with self._lock_guard():
            item = self.get(image_id)
            if not item:
                return False
            self._remove_item_locked(item)
            self.save()
            return True

    # ---------------- 清理 ----------------
    def _lock_guard(self):
        return self._lock

    def _remove_item_locked(self, item: dict[str, Any]) -> None:
        try:
            path = self.file_path(item)
            if path.is_file() and self.images_dir in path.parents:
                path.unlink()
        except Exception:
            pass
        try:
            self._data["items"].remove(item)
        except ValueError:
            pass

    def _enforce_limits_locked(self) -> list[dict[str, Any]]:
        now = _now()
        removed: list[dict[str, Any]] = []
        retention_seconds = self.retention_days * 86400

        for item in list(self._data["items"]):
            if item.get("favorite"):
                continue
            last_active = float(item.get("last_used_at") or item.get("created_at") or 0)
            if (
                now - last_active > retention_seconds
                and int(item.get("use_count") or 0) < self.min_uses
            ):
                removed.append(item)
                self._remove_item_locked(item)

        while len(self._data["items"]) > self.max_items:
            candidates = [
                item for item in self._data["items"] if not item.get("favorite")
            ]
            if not candidates:
                break
            candidates.sort(
                key=lambda item: (
                    int(item.get("use_count") or 0),
                    float(item.get("last_used_at") or item.get("created_at") or 0),
                    float(item.get("created_at") or 0),
                )
            )
            victim = candidates[0]
            removed.append(victim)
            self._remove_item_locked(victim)

        total = sum(int(item.get("size") or 0) for item in self._data["items"])
        while total > self.max_total_bytes:
            candidates = [
                item for item in self._data["items"] if not item.get("favorite")
            ]
            if not candidates:
                break
            candidates.sort(
                key=lambda item: (
                    int(item.get("use_count") or 0),
                    float(item.get("last_used_at") or item.get("created_at") or 0),
                )
            )
            victim = candidates[0]
            total -= int(victim.get("size") or 0)
            removed.append(victim)
            self._remove_item_locked(victim)

        return removed

    def cleanup(self) -> dict[str, Any]:
        with self._lock_guard():
            before = len(self._data["items"])
            removed = self._enforce_limits_locked()
            self._data["last_cleanup"] = _now()
            self.save()
            if removed:
                self._append_log(removed, "定期清理")
            return {
                "before": before,
                "removed": len(removed),
                "kept": len(self._data["items"]),
                "removed_ids": [item.get("id") for item in removed],
                "at": self._data["last_cleanup"],
            }

    def _append_log(self, removed: list[dict[str, Any]], reason: str) -> None:
        try:
            if self.log_path.is_file() and self.log_path.stat().st_size > 1024 * 1024:
                self.log_path.replace(self.log_path.with_suffix(".log.1"))
            stamp = time.strftime("%Y-%m-%d %H:%M:%S")
            ids = ", ".join(str(item.get("id")) for item in removed)
            with self.log_path.open("a", encoding="utf-8") as fh:
                fh.write(f"{stamp}\t{reason}\t{len(removed)} 张\t{ids}\n")
        except Exception:
            pass

    def stats(self) -> dict[str, Any]:
        with self._lock_guard():
            return self._stats_locked()

    def _stats_locked(self) -> dict[str, Any]:
        items = self._data["items"]
        total = sum(int(item.get("size") or 0) for item in items)
        now = _now()
        used = [item for item in items if int(item.get("use_count") or 0) > 0]
        auto_saved = sum(1 for item in items if item.get("source") == "auto")
        ages = [
            (now - float(item.get("created_at") or now)) / 86400 for item in items
        ]
        return {
            "count": len(items),
            "total_mb": round(total / 1024 / 1024, 2),
            "used_count": len(used),
            "never_used": len(items) - len(used),
            "auto_saved": auto_saved,
            "oldest_days": round(max(ages), 1) if ages else 0,
            "max_items": self.max_items,
            "retention_days": self.retention_days,
            "min_uses": self.min_uses,
            "last_cleanup": self._data.get("last_cleanup") or 0,
        }


class SaveRateLimiter:
    """限制“模型自行决定收藏”的频率。

    用户明确要求保存时不走这里；只有模型自主判断的收藏才受最小间隔和
    每日上限约束。状态文件放在图库目录，重启后仍然有效。
    """

    def __init__(
        self,
        root: str | Path,
        *,
        min_interval_minutes: int = 30,
        max_per_day: int = 10,
    ) -> None:
        self.path = Path(root).expanduser().resolve() / "auto_save_state.json"
        self.min_interval_minutes = max(0, int(min_interval_minutes))
        self.max_per_day = max(0, int(max_per_day))
        self._lock = threading.RLock()
        self._state = self._load()

    def _today(self, now: float | None = None) -> str:
        return time.strftime("%Y-%m-%d", time.localtime(now if now is not None else _now()))

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except Exception:
            data = {}
        return {
            "date": str(data.get("date") or ""),
            "count": int(data.get("count") or 0),
            "last_ts": float(data.get("last_ts") or 0),
        }

    def _save(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, self.path)

    def allow(self, now: float | None = None) -> tuple[bool, str]:
        with self._lock:
            moment = _now() if now is None else float(now)
            today = self._today(moment)
            if self._state.get("date") != today:
                self._state = {"date": today, "count": 0, "last_ts": 0.0}
                self._save(self._state)
            if self.max_per_day and int(self._state["count"]) >= self.max_per_day:
                return False, "今天自动收藏已经到上限"
            last_ts = float(self._state.get("last_ts") or 0)
            if (
                self.min_interval_minutes
                and last_ts
                and moment - last_ts < self.min_interval_minutes * 60
            ):
                return False, "距离上次自动收藏太近"
            return True, ""

    def record(self, now: float | None = None) -> None:
        with self._lock:
            moment = _now() if now is None else float(now)
            today = self._today(moment)
            if self._state.get("date") != today:
                self._state = {"date": today, "count": 0, "last_ts": 0.0}
            self._state["count"] = int(self._state.get("count") or 0) + 1
            self._state["last_ts"] = moment
            self._save(self._state)

    def status(self, now: float | None = None) -> dict[str, Any]:
        with self._lock:
            moment = _now() if now is None else float(now)
            count = (
                int(self._state.get("count") or 0)
                if self._state.get("date") == self._today(moment)
                else 0
            )
            return {
                "date": self._today(moment),
                "count": count,
                "max_per_day": self.max_per_day,
                "min_interval_minutes": self.min_interval_minutes,
                "last_ts": float(self._state.get("last_ts") or 0),
            }
