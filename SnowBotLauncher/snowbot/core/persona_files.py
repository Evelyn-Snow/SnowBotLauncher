"""Markdown 人格文件、占位符与本地人格库。"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from .paths import PERSONAS_DIR

PLACEHOLDER_RE = re.compile(r"\$?\{([A-Za-z][A-Za-z0-9_]*)\}")
_INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_stem(value: str, fallback: str = "persona") -> str:
    stem = _INVALID_FILENAME.sub("_", str(value or "").strip()).strip(" .")
    return stem[:80] or fallback


def render_persona(text: str, variables: dict) -> str:
    """替换 {OWNER_QQ}、{BOT_NAME} 等大写占位符；未知占位符原样保留。"""
    mapping = {str(k).upper(): "" if v is None else str(v) for k, v in variables.items()}

    def replace(match: re.Match) -> str:
        key = match.group(1)
        return mapping.get(key, match.group(0))

    return PLACEHOLDER_RE.sub(replace, str(text or ""))


def list_persona_files(directory: Path = PERSONAS_DIR) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    return sorted(
        (p for p in directory.glob("*.md") if p.is_file()),
        key=lambda p: p.name.lower(),
    )


def read_persona_file(path: Path) -> str:
    return Path(path).read_text(encoding="utf-8-sig")


def write_persona_file(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(text or "").replace("\r\n", "\n"), encoding="utf-8")


def import_persona_file(source: Path, directory: Path = PERSONAS_DIR, overwrite: bool = False) -> Path:
    """把外部 .md 复制进本地人格库，返回库内路径。"""
    source = Path(source)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{safe_stem(source.stem)}.md"
    if target.exists() and not overwrite and target.resolve() != source.resolve():
        raise FileExistsError(f"{target.name} 已存在")
    if target.resolve() != source.resolve():
        shutil.copy2(source, target)
    return target
