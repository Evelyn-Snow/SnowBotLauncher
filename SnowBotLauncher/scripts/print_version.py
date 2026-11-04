"""打印启动器版本号，供 build.bat 生成安装包时使用。"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
text = (ROOT / "snowbot" / "core" / "paths.py").read_text(encoding="utf-8")
match = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', text)
if not match:
    raise SystemExit("未找到 APP_VERSION")
print(match.group(1))
