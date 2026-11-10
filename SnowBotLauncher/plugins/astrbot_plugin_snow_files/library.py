"""发文件插件的纯逻辑：允许目录、路径校验、隐私关键词与内容扫描（可单测）。

只允许发送配置目录里的文件；路径解析后必须仍在目录内，不能借 ../、
绝对路径或符号链接跳出去。文件名/路径含隐私关键词、文本内容命中账号或
密钥特征的文件一律拒绝。
"""

from __future__ import annotations

import os
import re
from pathlib import Path

DEFAULT_EXTS = "md,txt,pdf,docx,pptx,xlsx,jpg,jpeg,png,gif,webp,zip"

# 目录/文件名里出现这些词就拒绝（防止把画像、日记、配置等文件发出去）
DEFAULT_DENY_KEYWORDS = (
    "画像", "关系", "日记", "记忆", "配置", "密码", "密钥", "令牌", "凭证",
    "隐私", "私密", "账号", "账户",
    "profile", "relation", "diary", "memory", "config", "secret", "token",
    "password", "cookie", "account", "credential", "state", "setting", ".env",
)

_SECRET_RE = re.compile(
    r"(?i)(password|passwd|api[_-]?key|secret[_-]?key|access[_-]?token|"
    r"cookie\s*[:=]|-----BEGIN [A-Z ]*PRIVATE KEY-----|sk-[A-Za-z0-9]{12,})"
)
_QQ_RE = re.compile(r"(?<!\d)(\d{5,12})(?!\d)")


def parse_exts(spec: str) -> set[str]:
    items = re.split(r"[,，\s]+", str(spec or ""))
    return {
        ("." + item.strip().lstrip(".").lower())
        for item in items
        if item.strip()
    }


def parse_roots(spec: str) -> list[Path]:
    """解析允许目录：每行/逗号一个，支持环境变量；空项忽略。"""
    items = re.split(r"[\r\n,，]+", str(spec or ""))
    roots = []
    for item in items:
        item = item.strip()
        if not item:
            continue
        roots.append(Path(os.path.expandvars(item)).expanduser())
    return roots


def is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def name_is_denied(relative_name: str, keywords: tuple[str, ...] | list[str]) -> bool:
    text = str(relative_name or "").lower()
    return any(str(word).lower() in text for word in keywords if str(word).strip())


def ext_allowed(path: Path, exts: set[str]) -> bool:
    return path.suffix.lower() in exts


def scan_text_file(path: Path, known_ids: set[str], max_bytes: int = 512 * 1024) -> str:
    """扫描文本文件：命中已知 QQ/账号或密钥特征时返回原因，否则返回空串。"""
    if path.suffix.lower() not in (".md", ".txt"):
        return ""
    try:
        with open(path, "rb") as f:
            raw = f.read(max_bytes)
    except Exception:
        return "读不了，按不安全处理"
    text = raw.decode("utf-8", errors="ignore")
    if _SECRET_RE.search(text):
        return "内容里像是有密钥或密码"
    ids = {str(item).strip() for item in known_ids if str(item).strip()}
    if ids:
        for match in _QQ_RE.finditer(text):
            if match.group(1) in ids:
                return "内容里出现了账号号码"
    return ""


def safe_file_in_roots(
    name: str,
    roots: list[Path],
) -> tuple[Path | None, str]:
    """把用户给的文件名解析到允许目录内；返回 (路径, 错误原因)。"""
    raw = str(name or "").strip().strip('"').strip("'")
    if not raw:
        return None, "没有给文件名"
    if ".." in raw.replace("\\", "/").split("/"):
        return None, "路径里不能有 .."
    candidate = Path(os.path.expandvars(raw)).expanduser()
    if candidate.is_absolute():
        for root in roots:
            if is_within(candidate, root) and candidate.is_file():
                return candidate.resolve(), ""
        return None, "这个路径不在允许发送的目录里"
    for root in roots:
        path = (root / raw).resolve()
        if is_within(path, root) and path.is_file():
            return path, ""
    # 只给文件名时在允许目录里递归找同名文件，取最新修改的那个
    hits = []
    target = Path(raw).name.lower()
    for root in roots:
        try:
            for path in root.rglob("*"):
                if path.is_file() and path.name.lower() == target and is_within(path, root):
                    hits.append(path)
        except OSError:
            continue
    if not hits:
        return None, "没找到这个文件"
    hits.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return hits[0].resolve(), ""


def list_files(
    roots: list[Path],
    exts: set[str],
    keywords: tuple[str, ...] | list[str],
    query: str = "",
    limit: int = 50,
) -> list[dict]:
    """列出允许目录里的可发送文件（已过滤扩展名和隐私关键词）。"""
    query = str(query or "").strip().lower()
    rows = []
    for root in roots:
        if not root.is_dir():
            continue
        try:
            for path in root.rglob("*"):
                if not path.is_file() or not is_within(path, root):
                    continue
                if not ext_allowed(path, exts):
                    continue
                try:
                    relative = path.relative_to(root).as_posix()
                except ValueError:
                    continue
                if name_is_denied(relative, keywords):
                    continue
                if query and query not in relative.lower():
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    continue
                rows.append(
                    {
                        "name": relative,
                        "path": path,
                        "size": stat.st_size,
                        "mtime": stat.st_mtime,
                    }
                )
        except OSError:
            continue
    rows.sort(key=lambda row: row["mtime"], reverse=True)
    return rows[: max(1, int(limit))]


def human_size(size: int) -> str:
    value = float(max(0, int(size or 0)))
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f}{unit}" if unit == "B" else f"{value:.1f}{unit}"
        value /= 1024
    return f"{value:.1f}GB"


def format_file_list(rows: list[dict], limit: int = 20) -> str:
    if not rows:
        return "我这边的文件夹里没有能发的文件。"
    lines = []
    for row in rows[:limit]:
        lines.append(f"- {row['name']}（{human_size(row['size'])}）")
    if len(rows) > limit:
        lines.append(f"……还有 {len(rows) - limit} 个")
    return "我能发的文件：\n" + "\n".join(lines)
