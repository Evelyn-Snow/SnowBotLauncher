"""图库的存储/检索/清理回归测试（不依赖 AstrBot）。"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from plugins.astrbot_plugin_snow_imagebox.library import (  # noqa: E402
    ImageLibrary,
    SaveRateLimiter,
    detect_extension,
    normalize_tags,
)


def png_bytes(seed: int) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + f"seed-{seed}".encode() + os.urandom(48)


class ImageBoxLibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="snow-imagebox-"))
        self.lib = ImageLibrary(
            self.tmp,
            max_items=10,
            retention_days=180,
            min_uses=2,
            max_file_mb=1,
            max_total_mb=10,
        )

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_tags_are_cleaned_and_deduplicated(self):
        self.assertEqual(normalize_tags("生气, 无语，生气、表情包"), ["生气", "无语", "表情包"])
        self.assertEqual(normalize_tags(""), ["未分类"])

    def test_detect_extension_from_header(self):
        self.assertEqual(detect_extension(png_bytes(1)), ".png")
        self.assertEqual(detect_extension(b"GIF89a" + b"x" * 8), ".gif")
        self.assertEqual(detect_extension(b"RIFF1234WEBP" + b"x"), ".webp")

    def test_save_deduplicate_and_search(self):
        data = png_bytes(1)
        item, status = self.lib.add_bytes(data, "生气的表情", "生气,无语")
        self.assertEqual(status, "saved")
        self.assertTrue((self.tmp / item["file"]).is_file())
        self.assertEqual(len(self.lib.items()), 1)

        same, status = self.lib.add_bytes(data, "生气的表情", "表情包")
        self.assertEqual(status, "duplicate")
        self.assertEqual(same["id"], item["id"])
        self.assertEqual(self.lib.items()[0]["tags"], ["生气", "无语", "表情包"])

        found = self.lib.search("生气")
        self.assertEqual([entry["id"] for entry in found], [item["id"]])
        self.assertEqual(self.lib.search("不存在的词"), [])

    def test_record_use_and_delete(self):
        item, _ = self.lib.add_bytes(png_bytes(2), "开心", "开心")
        self.lib.record_use(item["id"])
        self.assertEqual(self.lib.get(item["id"])["use_count"], 1)
        path = self.tmp / item["file"]
        self.assertTrue(self.lib.delete(item["id"]))
        self.assertFalse(path.exists())
        self.assertIsNone(self.lib.get(item["id"]))

    def test_cleanup_removes_old_unused(self):
        item, _ = self.lib.add_bytes(png_bytes(3), "旧图", "旧")
        internal = self.lib._data["items"][0]
        internal["created_at"] = 0
        internal["last_used_at"] = 0
        internal["use_count"] = 0
        self.lib.save()
        summary = self.lib.cleanup()
        self.assertEqual(summary["removed"], 1)
        self.assertFalse((self.tmp / item["file"]).exists())

    def test_cleanup_keeps_recently_used(self):
        item, _ = self.lib.add_bytes(png_bytes(4), "老但常用", "常用")
        internal = self.lib._data["items"][0]
        internal["created_at"] = 0
        internal["last_used_at"] = time.time()
        internal["use_count"] = 1
        self.lib.save()
        summary = self.lib.cleanup()
        self.assertEqual(summary["removed"], 0)
        self.assertIsNotNone(self.lib.get(item["id"]))

    def test_max_items_evicts_lowest_use(self):
        first = None
        for index in range(12):
            item, _ = self.lib.add_bytes(png_bytes(100 + index), f"图{index}", "批量")
            if first is None:
                first = item
            if index == 1:
                self.lib.record_use(item["id"])
                self.lib.record_use(item["id"])
        self.assertLessEqual(len(self.lib.items()), 10)
        self.assertIsNone(self.lib.get(first["id"]))

    def test_pick_returns_full_item_with_file(self):
        item, _ = self.lib.add_bytes(png_bytes(6), "被选中的图", "选中")
        picked = self.lib.pick("选中")
        self.assertIsNotNone(picked)
        self.assertEqual(picked["id"], item["id"])
        self.assertEqual(picked["file"], item["file"])
        self.assertTrue((self.tmp / picked["file"]).is_file())

    def test_stats(self):
        self.lib.add_bytes(png_bytes(5), "统计", "统计")
        stats = self.lib.stats()
        self.assertEqual(stats["count"], 1)
        self.assertEqual(stats["max_items"], 10)
        self.assertEqual(stats["retention_days"], 180)



class AutoSaveLimiterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="snow-auto-save-"))
        self.limiter = SaveRateLimiter(
            self.tmp, min_interval_minutes=30, max_per_day=2
        )

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_interval_and_daily_cap(self):
        day = time.mktime((2026, 10, 31, 12, 0, 0, 0, 0, -1))
        self.assertTrue(self.limiter.allow(day)[0])
        self.limiter.record(day)
        self.assertFalse(self.limiter.allow(day + 60)[0])
        self.assertTrue(self.limiter.allow(day + 31 * 60)[0])
        self.limiter.record(day + 31 * 60)
        ok, why = self.limiter.allow(day + 32 * 60)
        self.assertFalse(ok)
        self.assertIn("上限", why)

    def test_new_day_resets_count(self):
        day = time.mktime((2026, 10, 31, 12, 0, 0, 0, 0, -1))
        self.limiter.record(day)
        self.limiter.record(day + 60)
        self.assertFalse(self.limiter.allow(day + 120)[0])
        self.assertTrue(self.limiter.allow(day + 86400)[0])
        self.assertEqual(self.limiter.status(day + 86400)["count"], 0)

    def test_stats_counts_auto_saved(self):
        tmp = Path(tempfile.mkdtemp(prefix="snow-auto-stats-"))
        try:
            lib = ImageLibrary(tmp)
            lib.add_bytes(png_bytes(7), "自动收藏的图", "自动", source="auto")
            self.assertEqual(lib.stats()["auto_saved"], 1)
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)



class AutoSaveDenyMessageTests(unittest.TestCase):
    def test_skip_message_is_not_user_facing_refusal(self):
        from plugins.astrbot_plugin_snow_imagebox.library import AUTO_SAVE_SKIPPED

        self.assertNotIn("拒绝", AUTO_SAVE_SKIPPED)
        self.assertIn("不要重复", AUTO_SAVE_SKIPPED)
        self.assertIn("继续正常回复", AUTO_SAVE_SKIPPED)


if __name__ == "__main__":
    unittest.main()
