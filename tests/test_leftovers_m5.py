import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.engine.reflex_gate import ReflexGate
from core.self_model import FATIGUE_MAX, SelfModel
from core.skills import Skill, SkillRegistry
from core.tool_result import ToolFailure


START = 1_000_000.0


def _ego(**overrides):
    ego = SelfModel.__new__(SelfModel)
    ego.lock = threading.Lock()
    ego.fatigue_critical = 2.0
    ego.fatigue = 0.99
    ego.mood = 0.0
    ego.stress = 0.1
    ego.curiosity = 0.5
    ego.atp_level = 1.0
    ego.dopamine_receptors = 1.0
    ego.last_slept_time = START - 3 * 86400  # sleep-deprived
    ego.days_without_sleep = 0
    ego._sleep_warning_cooldown = False
    ego.memory_manager = None
    for name, value in overrides.items():
        setattr(ego, name, value)
    return ego


class FatigueScaleTests(unittest.TestCase):
    def _circadian(self, ego, hour, timestamps):
        fake_datetime = SimpleNamespace(now=lambda: SimpleNamespace(hour=hour, minute=30))
        with patch("core.self_model.datetime", fake_datetime), patch("builtins.print"):
            for ts in timestamps:
                with patch("core.self_model.time.time", return_value=ts):
                    ego.apply_circadian_rhythm()

    def test_sleep_deprivation_never_pushes_fatigue_above_one(self):
        ego = _ego()
        self._circadian(ego, 0, [START + i * 3600 for i in range(10)])
        self.assertLessEqual(ego.fatigue, FATIGUE_MAX)
        self.assertAlmostEqual(ego.fatigue, FATIGUE_MAX)

    def test_daily_tolerance_stays_on_the_fatigue_scale(self):
        ego = _ego()
        for roll in (0.01, 0.1, 0.5):
            with patch("core.self_model.random.random", return_value=roll):
                ego.reroll_thresholds()
            self.assertLessEqual(ego.fatigue_critical, FATIGUE_MAX)
            self.assertLessEqual(ego.fatigue_severe, ego.fatigue_critical)

    def test_legacy_fatigue_above_one_is_clamped_on_load(self):
        import json
        import tempfile
        from pathlib import Path

        from tests.test_self_model_load_m23 import _new_self_model

        model = _new_self_model()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ego.json"
            path.write_text(json.dumps({"fatigue": 2.5}), encoding="utf-8")
            with patch("core.self_model.time.time", return_value=10_000.0), patch(
                "core.self_model.os.path.getmtime", return_value=10_000.0
            ):
                self.assertTrue(model.load_state(str(path)))
        self.assertEqual(model.fatigue, FATIGUE_MAX)


class RelativeSleepReflexTests(unittest.TestCase):
    def _hits(self, fatigue, critical, trials=1000):
        gate = ReflexGate(SimpleNamespace(ego=SimpleNamespace(fatigue=fatigue, fatigue_critical=critical)))
        return sum(gate.evaluate_reflexes()["triggered"] for _ in range(trials))

    def test_fragile_day_says_goodnight_before_collapsing(self):
        # fatigue_critical=0.5: collapse at 0.5, so the graceful reflex must
        # already be likely just below it.
        self.assertGreater(self._hits(0.48, 0.5), 600)
        self.assertEqual(self._hits(0.3, 0.5), 0)

    def test_normal_day_matches_previous_behaviour(self):
        self.assertEqual(self._hits(0.7, 1.0), 0)
        self.assertGreater(self._hits(0.98, 1.0), 700)


class ToolFailureAccountingTests(unittest.TestCase):
    def _registry(self, func):
        registry = SkillRegistry()
        registry._save_unsafe = Mock()
        skill = Skill("probe", "probe", "probe|x", func)
        skill.mastery = 0.5
        skill.rust_level = 0.0
        registry.register(skill)
        return registry, skill

    def test_reported_failure_earns_no_mastery_or_reward(self):
        registry, skill = self._registry(lambda _args: ToolFailure("Lỗi tìm kiếm: offline"))
        ego = SimpleNamespace(register_reward=Mock(), lock=threading.Lock(), fatigue=0.0, stress=0.0)
        result = registry.execute("probe", "x", ego=ego)
        self.assertEqual(result, "Lỗi tìm kiếm: offline")
        self.assertIsInstance(result, str)
        self.assertEqual(skill.mastery, 0.5)
        ego.register_reward.assert_not_called()

    def test_success_still_earns_mastery_and_reward(self):
        registry, skill = self._registry(lambda _args: "kết quả")
        ego = SimpleNamespace(register_reward=Mock(), lock=threading.Lock(), fatigue=0.0, stress=0.0)
        registry.execute("probe", "x", ego=ego)
        self.assertAlmostEqual(skill.mastery, 0.6)
        ego.register_reward.assert_called_once_with("tool_success", 0.3)

    def test_web_search_error_is_a_failure(self):
        from core import tools

        with patch("core.tools.urllib.request.urlopen", side_effect=OSError("proxy")):
            result = tools.web_search("aura")
        self.assertIsInstance(result, ToolFailure)

    def test_reader_not_found_is_a_failure(self):
        import os
        import tempfile

        from components.reader import BackgroundReader

        with tempfile.TemporaryDirectory() as tmp:
            reader = BackgroundReader(None, sources=[], progress_path=os.path.join(tmp, "p.json"))
            self.assertIsInstance(reader.search_and_set_novel("x"), ToolFailure)


if __name__ == "__main__":
    unittest.main()
