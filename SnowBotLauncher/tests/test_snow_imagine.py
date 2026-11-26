"""snow_imagine 纯逻辑测试：构图选择、脱敏、衣橱与提示词。"""

from __future__ import annotations

import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from plugins.astrbot_plugin_snow_imagine.library import (  # noqa: E402
    build_prompt,
    character_anchors,
    choose_composition,
    choose_expression,
    choose_shot,
    sanitize_scene,
    wardrobe_for_scene,
)


SPEC = {
    "hair": "silver-white bob hair with ice-blue tips",
    "eyes": "glacier-blue eyes with small star highlights",
    "outfit": "deep blue-grey jacket, white collar",
    "wardrobe": {
        "daily_campus": {
            "outfit": "white knit cardigan and navy skirt",
            "shoes": "white canvas sneakers",
            "socks": "white lace short socks",
        },
        "library": {
            "outfit": "white cardigan and navy skirt",
            "shoes": "black Mary Janes",
        },
        "home_study": {
            "outfit": "oversized white shirt and low ponytail",
            "shoes": "",
        },
        "snow_night": {
            "outfit": "blue-grey formal coat and white cape",
            "shoes": "black ankle boots",
        },
    },
}


class ImagineLibraryTests(unittest.TestCase):
    def test_sanitize_scene(self):
        self.assertEqual(sanitize_scene("密码是123"), "")
        self.assertNotIn("12345678", sanitize_scene("QQ12345678说桌上的书"))
        self.assertNotIn("http", sanitize_scene("看 https://example.com 的图"))
        self.assertNotIn("C:\\", sanitize_scene("C:\\Users\\a\\secret.txt"))
        self.assertEqual(sanitize_scene("桌上的书和茶"), "桌上的书和茶")

    def test_choose_composition(self):
        self.assertEqual(choose_composition("桌上的书和茶"), "scene")
        self.assertEqual(choose_composition("和朋友在食堂"), "group")
        self.assertEqual(choose_composition("跑出画面的一瞬间"), "candid")
        self.assertEqual(choose_composition("看看你现在的样子"), "portrait")
        self.assertEqual(
            choose_composition("看看你", allow_portrait=False), "partial"
        )
        self.assertIn(
            choose_composition("普通的一天", rng=random.Random(1)),
            {"scene", "partial", "candid", "group"},
        )

    def test_wardrobe_by_scene(self):
        self.assertIn("cardigan", wardrobe_for_scene(SPEC, "图书馆")["outfit"])
        self.assertIn("oversized", wardrobe_for_scene(SPEC, "书桌")["outfit"])
        self.assertIn("formal", wardrobe_for_scene(SPEC, "雪夜")["outfit"])
        self.assertIn("cardigan", wardrobe_for_scene(SPEC, "校园")["outfit"])

    def test_prompt_scene_has_no_character(self):
        prompt = build_prompt(
            "桌上的书和茶",
            composition="scene",
            spec=SPEC,
        )
        self.assertIn("NOT in frame", prompt)
        self.assertIn("no character", prompt)
        self.assertNotIn("silver-white bob", prompt)

    def test_prompt_partial_and_group(self):
        partial = build_prompt(
            "刚画完的速写",
            composition="partial",
            spec=SPEC,
        )
        self.assertIn("partially appears", partial)
        self.assertIn("silver-white bob", partial)
        group = build_prompt(
            "和同学在食堂",
            composition="group",
            spec=SPEC,
            allow_other_people=True,
        )
        self.assertIn("other people", group)
        self.assertIn("background", group)

    def test_shot_and_expression_presets(self):
        self.assertEqual(
            choose_shot("桌面", "leading_lines", composition="scene"), "leading_lines"
        )
        self.assertIn(
            choose_shot("桌面", composition="scene"),
            {"high_angle", "closeup", "leading_lines", "pov", "film"},
        )
        self.assertEqual(choose_expression("好困", composition="partial"), "sleepy")
        self.assertEqual(
            choose_expression("随便", "shy", composition="portrait"), "shy"
        )
        prompt = build_prompt(
            "图书馆窗边的书",
            composition="partial",
            spec=SPEC,
            shot="over_shoulder",
            expression="shy",
        )
        self.assertIn("over-the-shoulder", prompt)
        self.assertIn("shy blush", prompt)

    def test_wardrobe_new_outfits(self):
        spec = dict(SPEC)
        spec["wardrobe"] = dict(SPEC["wardrobe"])
        spec["wardrobe"].update(
            {
                "rainy_day": {"outfit": "trench coat"},
                "sport": {"outfit": "sport jacket"},
            }
        )
        self.assertIn("trench", wardrobe_for_scene(spec, "下雨了")["outfit"])
        self.assertIn("sport", wardrobe_for_scene(spec, "去跑步")["outfit"])
        self.assertEqual(
            wardrobe_for_scene(spec, "随便", "rainy_day")["outfit"], "trench coat"
        )

    def test_character_anchors(self):
        anchors = character_anchors(SPEC, wardrobe_for_scene(SPEC, "校园"))
        self.assertIn("silver-white bob", anchors)
        self.assertIn("star hairpin", anchors)
        self.assertIn("white knit cardigan", anchors)


if __name__ == "__main__":
    unittest.main()
