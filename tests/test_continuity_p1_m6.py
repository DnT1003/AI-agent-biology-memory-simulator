import datetime as dt
import os
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from core.engine import enrichment
from core.engine.life_log import LifeLog, recap_prompt
from core.engine.memory_ops import MemoryOperationsController
from core.prospective_memory import ProspectiveMemory
from core.temporal import describe_now, fuzzy_age, fuzzy_duration


def _ts(day, hour, minute=0):
    # 2026-10-19 is a Monday.
    return dt.datetime(2026, 10, 19 + day, hour, minute).timestamp()


class TemporalTests(unittest.TestCase):
    def test_fuzzy_ages_sound_like_a_person(self):
        now = _ts(3, 20)
        self.assertEqual(fuzzy_age(now - 600, now), "vừa nãy")
        self.assertEqual(fuzzy_age(now - 2 * 3600, now), "mấy tiếng trước")
        self.assertEqual(fuzzy_age(_ts(3, 8), now), "sáng nay")
        self.assertEqual(fuzzy_age(_ts(2, 15), now), "chiều hôm qua")
        self.assertEqual(fuzzy_age(_ts(2, 23), now), "đêm qua")
        self.assertEqual(fuzzy_age(_ts(1, 12), now), "hôm kia")
        self.assertEqual(fuzzy_age(now - 10 * 86400, now), "tuần trước")
        self.assertEqual(fuzzy_age(now - 400 * 86400, now), "lâu lắm rồi")
        self.assertEqual(fuzzy_age("garbage", now), "không nhớ rõ khi nào")

    def test_durations_and_now(self):
        self.assertEqual(fuzzy_duration(5 * 60), "một lúc")
        self.assertEqual(fuzzy_duration(5 * 3600), "khoảng 5 tiếng")
        self.assertEqual(fuzzy_duration(3 * 86400), "khoảng 3 ngày")
        self.assertEqual(describe_now(_ts(1, 20, 15)), "tối thứ Ba, 20/10/2026 20:15")


class FaintMemoryTests(unittest.TestCase):
    def _ops(self, fatigue=0.0):
        ops = object.__new__(MemoryOperationsController)
        ops.engine = SimpleNamespace(ego=SimpleNamespace(fatigue=fatigue))
        return ops

    def test_weak_memories_are_faint_flashbulbs_never(self):
        ops = self._ops()
        self.assertTrue(ops.is_faint(SimpleNamespace(strength=0.2, is_flashbulb=False)))
        self.assertFalse(ops.is_faint(SimpleNamespace(strength=0.4, is_flashbulb=False)))
        self.assertFalse(ops.is_faint(SimpleNamespace(strength=0.05, is_flashbulb=True)))
        self.assertTrue(self._ops(fatigue=0.9).is_faint(SimpleNamespace(strength=0.4, is_flashbulb=False)))

    def test_gist_keeps_the_first_clause_without_specifics(self):
        gist = MemoryOperationsController.faint_gist(
            "Anh kể đi ăn bún chả ở số 12 Hàng Mành. Quán đông lắm."
        )
        self.assertNotIn("Quán", gist)
        self.assertNotIn("12", gist)

    def test_name_mask_by_capital_letter_is_gone(self):
        ops = self._ops(fatigue=0.95)
        ops.engine.ego.stress = 0.0
        self.assertIn("Hà Nội", ops._apply_fog_masking("Anh ở Hà Nội lúc 10:30"))


class ProspectiveMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "p.json")
        self.memory = ProspectiveMemory(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def _interview(self):
        return [{"owner": "user", "about": "phỏng vấn", "keyword": "phỏng vấn", "due": "2026-10-21"}]

    def test_owner_event_is_followed_up_only_after_it_happened(self):
        self.memory.add(self._interview(), _ts(1, 19))
        self.assertEqual(self.memory.due_follow_ups(_ts(2, 12)), [])
        # Wishing luck before the event keeps it open.
        self.memory.mark_mentioned("chúc anh phỏng vấn may mắn", _ts(2, 12))
        due = self.memory.due_follow_ups(_ts(2, 20, 30))
        self.assertEqual([i.keyword for i in due], ["phỏng vấn"])
        self.memory.mark_mentioned("phỏng vấn thế nào rồi anh?", _ts(2, 21))
        self.assertEqual(self.memory.due_follow_ups(_ts(2, 22)), [])

    def test_aura_promise_is_kept_by_mentioning_it(self):
        self.memory.add([{"owner": "aura", "about": "kể tiếp chương 3", "keyword": "chương 3", "due": None}], _ts(0, 21))
        self.assertTrue(any("Bạn đã hứa" in line for line in self.memory.context_lines(_ts(1, 9))))
        self.memory.mark_mentioned("à em kể tiếp chương 3 nhé", _ts(1, 9))
        self.assertEqual(self.memory.relevant(_ts(1, 10)), [])

    def test_whole_batch_rejected_on_one_bad_item(self):
        with self.assertRaises(ValueError):
            self.memory.add(self._interview() + [{"owner": "someone", "about": "x", "keyword": "x"}], _ts(0, 9))
        self.assertEqual(self.memory.items, [])

    def test_duplicates_merge_and_items_expire(self):
        self.memory.add(self._interview(), _ts(0, 9))
        self.memory.add(self._interview(), _ts(0, 10))
        self.assertEqual(len(self.memory.items), 1)
        self.assertEqual(self.memory.relevant(_ts(10, 9)), [])

    def test_busy_is_capped_and_persisted(self):
        now = _ts(1, 9)
        self.memory.set_busy("2026-10-25 11:00", "đi họp", now)
        self.assertTrue(self.memory.is_busy(now + 3600))
        self.assertFalse(self.memory.is_busy(now + 13 * 3600))  # capped at 12 h
        self.memory.add(self._interview(), now)
        reloaded = ProspectiveMemory(self.path)
        self.assertEqual(len(reloaded.items), 1)
        self.assertTrue(reloaded.is_busy(now + 3600))


class EnrichmentTests(unittest.TestCase):
    def _engine(self, payload):
        return SimpleNamespace(
            llm=SimpleNamespace(generate_json=Mock(return_value=(payload, 0.0))),
            world_graph=SimpleNamespace(apply_extraction=Mock(return_value=True)),
            value_system=SimpleNamespace(update_user_values_batch=Mock()),
            prospective=ProspectiveMemory(None),
        )

    def test_one_call_feeds_every_store(self):
        engine = self._engine({
            "relations": [{"source": "User", "relation": "bạn", "target": "Minh", "valence": 0.5}],
            "values": [{"value": "Sự Thành Thật", "sentiment": 0.9}],
            "open_loops": [{"owner": "user", "about": "thi", "keyword": "thi", "due": "2026-10-22"}],
            "user_busy": {"until": "2026-10-19 11:00", "reason": "họp"},
        })
        outcome = enrichment.run_enrichment(engine, "x", "y", _ts(0, 9))
        self.assertEqual(engine.llm.generate_json.call_count, 1)
        self.assertTrue(all(outcome.values()), outcome)
        engine.world_graph.apply_extraction.assert_called_once()
        engine.value_system.update_user_values_batch.assert_called_once()
        self.assertEqual(len(engine.prospective.items), 1)
        self.assertTrue(engine.prospective.is_busy(_ts(0, 10)))

    def test_a_bad_section_does_not_block_the_others(self):
        engine = self._engine({
            "values": [{"value": "x", "sentiment": "very"}],
            "open_loops": [{"owner": "user", "about": "thi", "keyword": "thi", "due": None}],
        })
        outcome = enrichment.run_enrichment(engine, "x", "y", _ts(0, 9))
        self.assertFalse(outcome["values"])
        self.assertTrue(outcome["open_loops"])
        engine.value_system.update_user_values_batch.assert_not_called()

    def test_prompt_carries_the_date_for_relative_days(self):
        prompt = enrichment.build_prompt("thứ 4 anh phỏng vấn", "ok", _ts(1, 19))
        self.assertIn("thứ Ba, 20/10/2026", prompt)
        self.assertIn("open_loops", prompt)


class LifeLogTests(unittest.TestCase):
    def test_recap_only_after_a_real_gap_and_only_real_events(self):
        engine = SimpleNamespace(life_log=LifeLog())
        start = _ts(0, 12)
        engine.life_log.add("read", "[Số đỏ] Chương 3", start + 600)
        engine.life_log.add("read", "[Số đỏ] Chương 4", start + 1200)
        engine.life_log.add("sleep", "đi ngủ", start + 3600)
        self.assertEqual(recap_prompt(engine, start, start + 1800), "")
        recap = recap_prompt(engine, start, start + 5 * 3600)
        self.assertIn("khoảng 5 tiếng", recap)
        self.assertIn("Chương 4 (và 1 đoạn khác)", recap)
        self.assertIn("đi ngủ", recap)
        self.assertIn("đừng bịa thêm", recap)
        self.assertEqual(recap_prompt(engine, None, start), "")

    def test_quiet_gap_says_nothing_special(self):
        engine = SimpleNamespace(life_log=LifeLog())
        self.assertIn("không có gì đặc biệt", recap_prompt(engine, _ts(0, 8), _ts(0, 12)))


if __name__ == "__main__":
    unittest.main()
