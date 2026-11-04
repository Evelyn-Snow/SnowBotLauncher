"""校验版本号只有一个来源，避免安装包/文档漂移。"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


class VersionConsistencyTests(unittest.TestCase):
    def test_paths_version_present(self):
        match = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', read("snowbot/core/paths.py"))
        self.assertIsNotNone(match)
        self.assertRegex(match.group(1), r"^\d+\.\d+\.\d+$")

    def test_installer_reads_version_from_command_line(self):
        iss = read("installer/SnowBotLauncher.iss")
        self.assertIn("#ifndef MyAppVersion", iss)
        self.assertIn("/DMyAppVersion", read("build.bat"))
        self.assertIn("print_version.py", read("build.bat"))

    def test_readme_has_no_hardcoded_setup_version(self):
        readme = read("README.md")
        self.assertNotRegex(readme, r"SnowBotLauncher-Setup-\d+\.\d+\.\d+\.exe")


if __name__ == "__main__":
    unittest.main()
