import sys
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core.engine.bio_controller import BioController
from core.self_model import SelfModel


def _ego(**overrides):
    ego = SelfModel.__new__(SelfModel)
    ego.lock = threading.Lock()
    ego.mood = 0.0
    ego.stress = 0.1
    ego.fatigue = 0.3
    ego.atp_level = 1.0
    ego.social_need = 0.5
    ego.curiosity = 0.5
    ego.integrity = 1.0
    ego.dopamine_receptors = 1.0
    ego.bio_controller = BioController()
    for name, value in overrides.items():
        setattr(ego, name, value)
    return ego


def _fake_psutil(cpu, ram):
    return SimpleNamespace(
        cpu_percent=lambda: cpu,
        virtual_memory=lambda: SimpleNamespace(percent=ram),
    )


class BioControllerDtScalingTests(unittest.TestCase):
    def test_zero_dt_changes_nothing(self):
        controller = BioController()
        controller.sensitivities["stress"] = 1.5
        delta = controller.calculate_physiology_delta({"stress": 0.9}, {}, 0.0)
        self.assertEqual(delta["fatigue_delta"], 0.0)
        self.assertEqual(delta["atp_delta"], 0.0)
        self.assertEqual(controller.sensitivities["stress"], 1.5)

    def test_sensitization_depends_on_time_not_call_count(self):
        sparse = BioController()
        sparse.calculate_physiology_delta({"stress": 0.9}, {}, 3600.0)
        dense = BioController()
        for _ in range(120):
            dense.calculate_physiology_delta({"stress": 0.9}, {}, 30.0)
        self.assertAlmostEqual(sparse.sensitivities["stress"], 1.05, places=9)
        self.assertAlmostEqual(dense.sensitivities["stress"], 1.05, places=9)

    def test_desensitization_depends_on_time_not_call_count(self):
        controller = BioController()
        controller.sensitivities["stress"] = 1.5
        for _ in range(120):
            controller.calculate_physiology_delta({"stress": 0.1}, {}, 30.0)
        self.assertAlmostEqual(controller.sensitivities["stress"], 1.5 * 0.95, places=9)

    def test_jitter_scales_with_sqrt_dt(self):
        controller = BioController()
        with patch("core.engine.bio_controller.random.uniform", return_value=0.02):
            tick = controller.calculate_physiology_delta({"stress": 0.0}, {}, 36.0)
        # dt = 0.01h: drift 0.01 * 0.01, jitter 0.02 * sqrt(0.01)
        self.assertAlmostEqual(tick["fatigue_delta"], 0.0001 + 0.002, places=12)

    def test_deltas_are_not_rounded(self):
        controller = BioController()
        with patch("core.engine.bio_controller.random.uniform", return_value=0.0):
            delta = controller.calculate_physiology_delta({"stress": 0.0}, {}, 30.0)
        self.assertAlmostEqual(delta["fatigue_delta"], 0.01 * 30 / 3600, places=15)
        self.assertAlmostEqual(delta["atp_delta"], -0.05 * 30 / 3600, places=15)


class SelfModelDtScalingTests(unittest.TestCase):
    def test_update_state_does_not_touch_sensitivities(self):
        ego = _ego(stress=0.9, is_stranger=False, mood_anchor=0.0,
                   mood_anchor_duration=float("inf"), resilience=0.0)
        ego.bio_controller.sensitivities["stress"] = 1.5
        with patch("builtins.print"):
            for _ in range(50):
                ego.update_state({"valence": 0.0, "arousal": 0.0})
        self.assertEqual(ego.bio_controller.sensitivities["stress"], 1.5)

    def test_embodiment_load_is_rate_based(self):
        ego = _ego()
        with patch.dict(sys.modules, {"psutil": _fake_psutil(100.0, 100.0)}), \
                patch("core.engine.bio_controller.random.uniform", return_value=0.0), \
                patch("builtins.print"):
            for _ in range(10):
                ego.apply_biological_decay(30.0, 0.0)
        hours = 300.0 / 3600.0
        expected_fatigue = 0.3 + (0.01 + 0.1 * 0.04) * hours + 0.1 * hours
        self.assertLess(ego.fatigue, 0.32)
        self.assertGreater(ego.fatigue, 0.3)
        self.assertAlmostEqual(ego.stress, 0.1 + 0.05 * hours, places=3)
        self.assertAlmostEqual(ego.fatigue, expected_fatigue, places=3)

    def test_circadian_no_longer_restores_dopamine_receptors(self):
        ego = _ego(dopamine_receptors=0.2, fatigue_critical=1.0,
                   last_slept_time=1_000_000.0, days_without_sleep=0,
                   _sleep_warning_cooldown=False, memory_manager=None)
        fake_datetime = SimpleNamespace(now=lambda: SimpleNamespace(hour=10, minute=0))
        with patch("core.self_model.datetime", fake_datetime), \
                patch("core.self_model.time.time", return_value=1_000_000.0):
            for _ in range(100):
                ego.apply_circadian_rhythm()
        self.assertEqual(ego.dopamine_receptors, 0.2)


if __name__ == "__main__":
    unittest.main()
