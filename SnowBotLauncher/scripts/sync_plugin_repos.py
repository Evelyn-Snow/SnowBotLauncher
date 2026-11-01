"""把 plugins/ 下的自研插件同步成可发布的独立仓库（AstrBot 插件市场要求一插件一仓库）。

用法：
    python scripts/sync_plugin_repos.py          # 同步到 ../plugin-releases/<插件名>/
    python scripts/sync_plugin_repos.py --init   # 同步并对每个目录执行 git init + 首次提交

发布流程见 docs/publishing.md。改 GitHub 用户名只需改下面的 OWNER。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

OWNER = "Evelyn-Snow"
LICENSE_HOLDER = "Evelyn-Snow"

ROOT = Path(__file__).resolve().parents[1]
PLUGINS_DIR = ROOT / "plugins"
RELEASES_ROOT = ROOT.parent / "plugin-releases"
SUBMIT_DIR = RELEASES_ROOT / "_submit"

LICENSE_TEXT = """MIT License

Copyright (c) 2026 {holder}

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

IGNORE = {"__pycache__", ".pytest_cache"}


def parse_metadata(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    lists: dict[str, list[str]] = {}
    current: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("  - ") and current is not None:
            lists.setdefault(current, []).append(line[4:].strip())
            continue
        if ":" in line and not line.startswith(" "):
            key, _, value = line.partition(":")
            key = key.strip()
            values[key] = value.strip()
            current = key if not value.strip() else None
    for key, items in lists.items():
        values[key] = "、".join(items)
    return values


def copy_tree(src: Path, dest: Path) -> None:
    for item in src.iterdir():
        if item.name in IGNORE or item.suffix == ".pyc":
            continue
        target = dest / item.name
        if item.is_dir():
            shutil.copytree(item, target, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy2(item, target)


def issue_text(meta: dict[str, str], repo_url: str) -> str:
    return f"""### 插件名称

{meta.get("name", "")}

### 插件仓库

{repo_url}

### 插件简介

{meta.get("desc", "")}

### 功能说明

{meta.get("help", "")}

### 版本

{meta.get("version", "")}

### 支持平台

{meta.get("support_platforms", "").replace("- ", "").replace(chr(10), "、").strip("、")}

### 依赖

见仓库 requirements.txt 与 README「依赖」一节；无第三方依赖时为纯标准库实现。
"""


def git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def main() -> int:
    if "--init" in sys.argv and shutil.which("git") is None:
        print("未找到 git，无法 --init；请先安装 Git 或去掉该参数。")
        return 1
    SUBMIT_DIR.mkdir(parents=True, exist_ok=True)
    synced = []
    for src in sorted(PLUGINS_DIR.glob("astrbot_plugin_*")):
        if not (src / "metadata.yaml").is_file():
            continue
        name = src.name
        dest = RELEASES_ROOT / name
        dest.mkdir(parents=True, exist_ok=True)
        # 清掉旧内容（保留 .git），保证发布目录与源码严格一致
        for item in dest.iterdir():
            if item.name == ".git":
                continue
            shutil.rmtree(item) if item.is_dir() else item.unlink()
        copy_tree(src, dest)
        (dest / "LICENSE").write_text(
            LICENSE_TEXT.format(holder=LICENSE_HOLDER), encoding="utf-8", newline="\n"
        )
        meta = parse_metadata(src / "metadata.yaml")
        repo_url = f"https://github.com/{OWNER}/{name}"
        (SUBMIT_DIR / f"{name}-issue.md").write_text(
            issue_text(meta, repo_url), encoding="utf-8", newline="\n"
        )
        if "--init" in sys.argv and not (dest / ".git").is_dir():
            git("init", "-b", "main", cwd=dest)
            git("add", "-A", cwd=dest)
            # 新仓库没有全局身份时也能提交；用 GitHub noreply 地址避免暴露邮箱
            git(
                "-c", f"user.name={OWNER}",
                "-c", f"user.email={OWNER}@users.noreply.github.com",
                "commit", "-m", f"release {meta.get('version', 'v0.1.0')}",
                cwd=dest,
            )
        synced.append(name)
        print(f"同步 {name} -> {dest}")
    print(f"\n共 {len(synced)} 个插件。提审文本在 {SUBMIT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
