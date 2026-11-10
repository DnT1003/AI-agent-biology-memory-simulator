import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core import relationship
from core.prompts import get_perceive_prompt
from core.sim_week import run_week


def _ego(**kw):
    ego = SimpleNamespace(relational_friction=0.0, current_intimacy=0.5, mood=0.3,
                          fatigue=0.1, fatigue_severe=0.8, boredom=0.0, embarrassed_at=0.0)
    for key, value in kw.items():
        setattr(ego, key, value)
    return ego


class _Rng:
    def __init__(self, value):
        self.value = value

    def random(self):
        return self.value

    def choice(self, items):
        return items[0]


class RuptureRepairTests(unittest.TestCase):
    def test_harsh_words_hurt_and_linger_through_cheerful_messages(self):
        ego = _ego()
        self.assertEqual(relationship.update_friction(ego, "Em phiền quá đấy! Đừng nhắn anh nữa", -0.6), "hurt")
        hurt = ego.relational_friction
        self.assertGreaterEqual(hurt, 0.5)
        self.assertIn("[KHÚC MẮC]", relationship.friction_prompt(ego))
        # A cheerful message is not a repair.
        self.assertEqual(relationship.update_friction(ego, "Hôm nay trời đẹp ghê", 0.7), "")
        self.assertEqual(ego.relational_friction, hurt)

    def test_apology_repairs_and_brings_them_closer(self):
        ego = _ego(relational_friction=0.5)
        self.assertEqual(relationship.update_friction(ego, "Anh xin lỗi, anh nói nặng lời quá", -0.3), "repair")
        self.assertAlmostEqual(ego.relational_friction, 0.2)
        self.assertAlmostEqual(ego.current_intimacy, 0.53)
        self.assertEqual(relationship.friction_prompt(ego), "")

    def test_apology_without_a_rift_changes_nothing(self):
        ego = _ego()
        self.assertEqual(relationship.update_friction(ego, "Anh xin lỗi vì về muộn", 0.0), "")
        self.assertEqual(ego.current_intimacy, 0.5)

    def test_strong_negative_aimed_at_her_counts_as_hostile(self):
        self.assertTrue(relationship.is_hostile("em làm anh thất vọng quá", -0.7))
        self.assertFalse(relationship.is_hostile("hôm nay anh thất vọng về công việc", -0.7))

    def test_time_softens_friction_faster_when_close(self):
        close = relationship.ease_friction(0.6, 8 * 3600, intimacy=0.9)
        distant = relationship.ease_friction(0.6, 8 * 3600, intimacy=0.1)
        self.assertLess(close, distant)
        self.assertLess(distant, 0.6)


class RefusalTests(unittest.TestCase):
    def test_reasons_are_visible_and_urgent_help_always_wins(self):
        self.assertEqual(relationship.refusal_prompt(_ego(), urgency=0.0), "")
        tired_and_sulking = _ego(fatigue=0.85, relational_friction=0.4)
        prompt = relationship.refusal_prompt(tired_and_sulking, urgency=0.0)
        self.assertIn("bạn đang mệt", prompt)
        self.assertIn("bạn đang dỗi User", prompt)
        self.assertIn("phải nói rõ lý do", prompt)
        self.assertIn("[VIỆC GẤP]", relationship.refusal_prompt(tired_and_sulking, urgency=0.8))

    def test_persona_is_a_partner_not_a_servant(self):
        import inspect

        source = inspect.getsource(get_perceive_prompt)
        self.assertNotIn("trung thành", source)
        self.assertIn("không phải trợ lý hay người hầu", source)


class EmbarrassmentTests(unittest.TestCase):
    def test_being_corrected_embarrasses_for_a_while(self):
        ego = _ego()
        now = 1_000_000.0
        self.assertIn("vừa chỉ ra bạn nhớ/nói sai", relationship.embarrassment_prompt(ego, "Không phải thế, là thứ 4 cơ", now))
        self.assertIn("vẫn còn hơi ngượng", relationship.embarrassment_prompt(ego, "ừ", now + 10 * 60))
        self.assertEqual(relationship.embarrassment_prompt(ego, "ừ", now + 60 * 60), "")


class InsideJokeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.jokes = relationship.InsideJokes(os.path.join(self.tmp.name, "j.json"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_only_shared_laughter_is_remembered(self):
        self.assertTrue(self.jokes.remember("Quán bún chả đông kinh khủng haha", 0.6, 0.0))
        self.assertFalse(self.jokes.remember("Quán bún chả đông kinh khủng haha", 0.6, 1.0))  # duplicate
        self.assertFalse(self.jokes.remember("Anh buồn quá haha", -0.5, 0.0))
        self.assertFalse(self.jokes.remember("Hôm nay đi làm", 0.6, 0.0))
        self.assertEqual(len(relationship.InsideJokes(self.jokes.path).jokes), 1)

    def test_callbacks_need_closeness_and_a_48h_rest(self):
        self.jokes.remember("Quán bún chả đông kinh khủng haha", 0.6, 0.0)
        close = _ego(current_intimacy=0.8)
        self.assertIsNone(self.jokes.pick(_ego(current_intimacy=0.5), 7200, rng=_Rng(0.0)))
        self.assertIsNone(self.jokes.pick(close, 600, rng=_Rng(0.0)))  # too fresh
        self.assertIsNone(self.jokes.pick(close, 7200, rng=_Rng(0.9)))  # not this time
        joke = self.jokes.pick(close, 7200, rng=_Rng(0.0))
        self.assertIsNotNone(joke)
        self.assertIsNone(self.jokes.pick(close, 7200 + 3600, rng=_Rng(0.0)))
        self.assertIsNotNone(self.jokes.pick(close, 7200 + 49 * 3600, rng=_Rng(0.0)))
        self.assertIsNone(self.jokes.pick(_ego(current_intimacy=0.8, relational_friction=0.4), 10**6, rng=_Rng(0.0)))
        self.assertIn("đùa riêng", relationship.joke_prompt(joke, 7200))


class FrictionPersistenceTests(unittest.TestCase):
    def test_friction_survives_a_restart(self):
        from tests.test_self_model_load_m23 import _new_self_model

        model = _new_self_model()
        model.relational_friction = 0.42
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ego.json")
            model.save_state(path)
            loaded = _new_self_model()
            with patch("core.self_model.os.path.getmtime", return_value=__import__("time").time()):
                self.assertTrue(loaded.load_state(path))
        self.assertAlmostEqual(loaded.relational_friction, 0.42)


class SimulationP3Tests(unittest.TestCase):
    def test_quarrel_and_repair_in_the_week(self):
        report = run_week(seed=7)
        trace = dict(report.friction_after_message)
        self.assertGreaterEqual(trace["Fri 18:10"], 0.4)   # "Em phiền quá đấy!..."
        self.assertLess(trace["Fri 18:40"], 0.25)           # after the apology
        self.assertGreaterEqual(report.prompt_markers["[KHÚC MẮC]"], 1)
        self.assertGreaterEqual(report.prompt_markers["[NGƯỢNG]"], 1)
        self.assertGreaterEqual(report.inside_jokes, 1)


if __name__ == "__main__":
    unittest.main()
