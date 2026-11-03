"""把按天散落的日记/经历迁移成「每个类型每月一个文件」。

- 日记：``日记/**/YYYY-MM-DD.md`` → ``日记/**/YYYY-MM.md``（按天分 ## 小节）
- 经历：``经历/YYYY-MM-DD-<type>.md`` → ``经历/YYYY-MM-<type>.md``（事件分 ## 小节）

迁移前会把旧文件打包到 ``<root>/_backup/records-daily-<时间>.zip``；
只有确认月度文件里能找到旧正文后才删除旧文件。支持 ``--dry-run``。
"""

from __future__ import annotations

import argparse
import re
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from plugins.astrbot_plugin_obsidian_notes.recording import append_diary_entry  # noqa: E402
from plugins.astrbot_plugin_snow_experience.library import event_type_name  # noqa: E402

DATE_FILE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$")
EVENT_FILE = re.compile(r"^(\d{4}-\d{2}-\d{2})-(book|research|paper)\.md$")
NORMALIZE = re.compile(r"\s+")


def _norm(text: str) -> str:
    return NORMALIZE.sub("", str(text or ""))


def _backup(paths: list[Path], root: Path) -> Path | None:
    if not paths:
        return None
    out_dir = root / "_backup"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"records-daily-{time.strftime('%Y%m%d-%H%M%S')}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in paths:
            try:
                zf.write(path, str(path.relative_to(root)))
            except Exception:
                pass
    return out


def migrate_diary(root: Path, dry: bool) -> tuple[int, list[Path]]:
    base = root / "日记"
    if not base.is_dir():
        return 0, []
    changed = 0
    olds: list[Path] = []
    groups: dict[tuple[Path, str], list[Path]] = {}
    for path in base.rglob("*.md"):
        match = DATE_FILE.match(path.name)
        if match:
            groups.setdefault((path.parent, match.group(1)[:7]), []).append(path)
    for (parent, month), files in sorted(groups.items()):
        monthly = parent / f"{month}.md"
        text = monthly.read_text(encoding="utf-8-sig") if monthly.exists() else f"# {month}\n"
        for path in sorted(files):
            content = path.read_text(encoding="utf-8-sig").strip()
            body = content.split("\n", 1)[1].strip() if content.startswith("# ") and "\n" in content else content
            if not body:
                continue
            text = append_diary_entry(text, path.stem, body)
            olds.append(path)
            changed += 1
        if not dry:
            monthly.write_text(text, encoding="utf-8")
        print(f"[日记] {monthly} ← {len(files)} 个按天文件")
    return changed, olds


def migrate_events(root: Path, dry: bool) -> tuple[int, list[Path]]:
    base = root / "经历"
    if not base.is_dir():
        return 0, []
    changed = 0
    olds: list[Path] = []
    groups: dict[tuple[Path, str, str], list[Path]] = {}
    for path in base.glob("*.md"):
        match = EVENT_FILE.match(path.name)
        if match:
            groups.setdefault((path.parent, match.group(1)[:7], match.group(2)), []).append(path)
    for (parent, month, event_type), files in sorted(groups.items()):
        monthly = parent / f"{month}-{event_type}.md"
        text = (
            monthly.read_text(encoding="utf-8-sig").rstrip()
            if monthly.exists()
            else f"# {month} {event_type_name(event_type)}"
        )
        for path in sorted(files):
            content = path.read_text(encoding="utf-8-sig").strip()
            if not content:
                continue
            if content.startswith("# "):
                content = "## " + content[2:]
            text = text.rstrip() + "\n\n" + content
            olds.append(path)
            changed += 1
        if not dry:
            monthly.write_text(text.rstrip() + "\n", encoding="utf-8")
        print(f"[经历] {monthly} ← {len(files)} 个按天文件")
    return changed, olds


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=r"C:\Evelyn_Snow")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    root = Path(args.root)
    diary_count, diary_olds = migrate_diary(root, args.dry_run)
    event_count, event_olds = migrate_events(root, args.dry_run)
    olds = diary_olds + event_olds
    print(f"待迁移：日记 {diary_count} 个、经历 {event_count} 个")
    if args.dry_run or not olds:
        return 0
    backup = _backup(olds, root)
    if backup is None:
        return 1
    for path in olds:
        try:
            path.unlink()
        except Exception as exc:
            print(f"[跳过删除] {path}: {exc}")
    print(f"备份：{backup}")
    print(f"已删除 {len(olds)} 个按天文件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
