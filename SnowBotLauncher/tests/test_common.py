"""启动器通用工具测试。"""

from __future__ import annotations

import socket
import tempfile
import unittest
from pathlib import Path

from snowbot.core.common import normalize_base_url, port_snapshot, read_json, write_json_atomic


class CommonTests(unittest.TestCase):
    def test_normalize_base_url(self):
        self.assertEqual(normalize_base_url("127.0.0.1:6185/"), "http://127.0.0.1:6185")
        self.assertEqual(normalize_base_url("https://x/"), "https://x")
        self.assertEqual(normalize_base_url("  "), "")

    def test_atomic_json_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.json"
            write_json_atomic(path, {"中文": [1, 2]})
            self.assertEqual(read_json(path), {"中文": [1, 2]})
            self.assertEqual(read_json(Path(tmp) / "missing.json", {}), {})

    def test_port_snapshot_closed_port(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        self.assertFalse(port_snapshot(port).get("listening"))


if __name__ == "__main__":
    unittest.main()
