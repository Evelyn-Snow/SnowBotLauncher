"""snow_memory 的纯逻辑与存储测试（不依赖运行中的 AstrBot）。"""

from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from plugins.astrbot_plugin_snow_memory.library import (  # noqa: E402
    audience_visible,
    build_extraction_prompt,
    build_insight_prompt,
    extract_json_object,
    fact_search_text,
    render_memory_block,
    score_candidate,
    text_similarity,
    validate_fact,
    validate_insight,
)
from plugins.astrbot_plugin_snow_memory.store import MemoryStore  # noqa: E402


def make_fact(**overrides):
    fact = {
        "subject": "哥哥",
        "subject_key": "哥哥",
        "subject_type": "person",
        "predicate": "likes",
        "object": "红烧肉",
        "object_key": "红烧肉",
        "object_type": "food",
        "fact_type": "preference",
        "polarity": 1,
        "confidence": 0.9,
        "importance": 0.6,
        "privacy": 2,
        "scope": "napcat:FriendMessage:1",
        "valid_from": time.time(),
        "search_text": "哥哥 喜欢 红烧肉",
        "source_event_ids": [1],
        "evidence": "我喜欢红烧肉",
    }
    fact.update(overrides)
    return fact


class MemoryLibraryTests(unittest.TestCase):
    def test_validate_fact_requires_evidence(self):
        events_text = "哥哥：我今天想吃红烧肉。"
        good = validate_fact(
            {
                "subject": "哥哥",
                "predicate": "likes",
                "object": "红烧肉",
                "fact_type": "preference",
                "confidence": 0.9,
                "privacy": 2,
                "evidence": "我今天想吃红烧肉",
            },
            events_text=events_text,
            default_ts=1000,
        )
        self.assertIsNotNone(good)
        self.assertEqual(good["predicate"], "likes")
        self.assertEqual(good["valid_from"], 1000)
        bad = validate_fact(
            {
                "subject": "哥哥",
                "predicate": "likes",
                "object": "红烧肉",
                "evidence": "他从来不吃肉",
            },
            events_text=events_text,
            default_ts=1000,
        )
        self.assertIsNone(bad)

    def test_validate_fact_caps_privacy_and_normalizes_predicate(self):
        fact = validate_fact(
            {
                "subject": "哥哥",
                "predicate": "喜欢",
                "object": "红烧肉",
                "privacy": 4,
                "evidence": "我喜欢红烧肉",
            },
            events_text="我喜欢红烧肉",
            default_ts=1000,
            max_privacy=4,
            aliases={"哥哥": "哥哥"},
        )
        self.assertEqual(fact["privacy"], 1)
        self.assertEqual(fact["predicate"], "likes")
        capped = validate_fact(
            {
                "subject": "小明",
                "predicate": "likes",
                "object": "篮球",
                "privacy": 4,
                "evidence": "小明喜欢篮球",
            },
            events_text="小明喜欢篮球",
            default_ts=1000,
            max_privacy=3,
        )
        self.assertEqual(capped["privacy"], 3)
        other = validate_fact(
            {
                "subject": "小明",
                "predicate": "likes",
                "object": "篮球",
                "privacy": 4,
                "evidence": "小明喜欢篮球",
            },
            events_text="小明喜欢篮球",
            default_ts=1000,
        )
        self.assertEqual(other["privacy"], 2)

    def test_audience_privacy_matrix(self):
        owner_private = make_fact(privacy=1, scope="owner")
        friend_private = make_fact(
            subject="小明", subject_key="小明", privacy=2, scope="friend"
        )
        group_fact = make_fact(privacy=3, scope="group:a")
        public = make_fact(privacy=4, scope="group:a")
        owner = {"is_owner": True, "sender_id": "1", "sender_name": "哥哥", "scope": "owner"}
        friend = {"is_owner": False, "sender_id": "2", "sender_name": "小明", "scope": "friend"}
        other_group = {"is_owner": False, "sender_id": "2", "sender_name": "小明", "scope": "group:b"}
        same_group = {"is_owner": False, "sender_id": "2", "sender_name": "小明", "scope": "group:a"}
        self.assertTrue(audience_visible(owner_private, owner))
        self.assertFalse(audience_visible(owner_private, friend))
        self.assertFalse(audience_visible(owner_private, same_group))
        owner_in_group = {
            "is_owner": True,
            "sender_id": "1",
            "sender_name": "哥哥",
            "scope": "group:a",
            "is_group": True,
        }
        self.assertFalse(audience_visible(owner_private, owner_in_group))
        self.assertTrue(audience_visible(friend_private, friend))
        self.assertFalse(audience_visible(friend_private, other_group))
        self.assertFalse(audience_visible(friend_private, same_group))
        self.assertTrue(audience_visible(group_fact, same_group))
        self.assertFalse(audience_visible(group_fact, other_group))
        self.assertTrue(audience_visible(public, other_group))
        secret = make_fact(privacy=0)
        self.assertFalse(audience_visible(secret, owner))

    def test_render_memory_block(self):
        block = render_memory_block(
            [make_fact()],
            [
                {
                    "statement": "他感冒时更愿意被提醒吃药",
                    "evidence_fact_ids": [1, 2],
                }
            ],
            limit_chars=900,
        )
        self.assertIn("[记忆]", block)
        self.assertIn("红烧肉", block)
        self.assertIn("[我的认识]", block)
        self.assertIn("依据2条事实", block)
        empty = render_memory_block([], [], abstain_hint=True)
        self.assertIn("没有可靠印象", empty)

    def test_score_prefers_relevant_recent_fact(self):
        now = time.time()
        relevant = make_fact(search_text="哥哥 喜欢 红烧肉", valid_from=now - 86400)
        irrelevant = make_fact(
            subject="小明",
            subject_key="小明",
            object="篮球",
            object_key="篮球",
            search_text="小明 喜欢 篮球",
            valid_from=now - 300 * 86400,
        )
        s1 = score_candidate(
            relevant,
            query="红烧肉",
            now=now,
            similarity=text_similarity("红烧肉", relevant["search_text"]),
        )
        s2 = score_candidate(
            irrelevant,
            query="红烧肉",
            now=now,
            similarity=text_similarity("红烧肉", irrelevant["search_text"]),
        )
        self.assertGreater(s1, s2)

    def test_insight_requires_real_fact_ids(self):
        good = validate_insight(
            {
                "scope": "other:哥哥",
                "insight_type": "pattern",
                "statement": "他感冒时更愿意被提醒吃药",
                "confidence": 0.8,
                "privacy": 2,
                "evidence_fact_ids": [1, 2, 3],
            },
            fact_ids={1, 2, 3},
            default_scope="other:哥哥",
        )
        self.assertIsNotNone(good)
        self.assertEqual(good["evidence_fact_ids"], [1, 2, 3])
        bad = validate_insight(
            {
                "statement": "他喜欢篮球",
                "evidence_fact_ids": [99],
            },
            fact_ids={1, 2},
            default_scope="other:哥哥",
        )
        self.assertIsNone(bad)
        single = validate_insight(
            {
                "statement": "他喜欢篮球",
                "evidence_fact_ids": [1],
            },
            fact_ids={1, 2},
            default_scope="other:哥哥",
        )
        self.assertIsNone(single)

    def test_prompts_and_json_extraction(self):
        prompt = build_extraction_prompt(
            [{"id": 1, "ts": 1000, "source": "chat", "sender_name": "哥哥", "text": "我喜欢红烧肉"}]
        )
        self.assertIn("evidence", prompt)
        self.assertIn("privacy", prompt)
        insight_prompt = build_insight_prompt("哥哥", [make_fact(id=1)])
        self.assertIn("evidence_fact_ids", insight_prompt)
        data = extract_json_object('```json\n{"facts":[]}\n```')
        self.assertEqual(data, {"facts": []})


class MemoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = MemoryStore(Path(self.tmp.name) / "memory.db")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_event_dedup_and_pending(self):
        kwargs = dict(
            event_key="k1",
            ts=1000,
            umo="u",
            role="user",
            text="我喜欢红烧肉",
        )
        self.assertTrue(self.store.add_event(**kwargs))
        self.assertFalse(self.store.add_event(**kwargs))
        self.assertEqual(len(self.store.pending_events()), 1)
        self.store.mark_processed([1])
        self.assertEqual(self.store.pending_events(), [])

    def test_fact_lifecycle_and_supersede(self):
        old_id = self.store.add_fact(make_fact(valid_from=1000))
        self.assertEqual(len(self.store.active_facts()), 1)
        new_id = self.store.add_fact(
            make_fact(
                object="牛肉",
                object_key="牛肉",
                valid_from=2000,
                search_text="哥哥 喜欢 牛肉",
            )
        )
        self.store.supersede_fact(old_id, new_id, valid_to=2000, now=2500)
        active = self.store.active_facts()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["object"], "牛肉")
        self.assertEqual(self.store.find_active("哥哥", "likes")[0]["id"], new_id)

    def test_insight_store(self):
        insight = {
            "scope": "other:哥哥",
            "insight_type": "pattern",
            "statement": "他感冒时更愿意被提醒吃药",
            "confidence": 0.8,
            "importance": 0.7,
            "privacy": 2,
            "evidence_fact_ids": [1],
            "search_text": "感冒 提醒吃药",
        }
        insight_id = self.store.add_insight(insight)
        self.assertGreater(insight_id, 0)
        active = self.store.active_insights()
        self.assertEqual(len(active), 1)
        self.assertIn("吃药", active[0]["statement"])

    def test_stats(self):
        self.store.add_event(
            event_key="k1", ts=1, umo="u", role="user", text="hi"
        )
        self.store.add_fact(make_fact())
        stats = self.store.stats()
        self.assertEqual(stats["events"], 1)
        self.assertEqual(stats["facts"], 1)
        self.assertEqual(stats["active_facts"], 1)


if __name__ == "__main__":
    unittest.main()
