import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core.self_model import SelfModel


START = 1_000_000.0


def _ego(**overrides):
    ego = SelfModel.__new__(SelfModel)
    ego.lock = threading.Lock()
    ego.fatigue_critical = 1.0
    ego.fatigue = 0.3
    ego.mood = 0.0
    ego.stress = 0.1
    ego.curiosity = 0.5
    ego.atp_level = 1.0
    ego.dopamine_receptors = 1.0
    ego.last_slept_time = START
    ego.days_without_sleep = 0
    ego._sleep_warning_cooldown = False
    ego.memory_manager = None
    for name, value in overrides.items():
        setattr(ego, name, value)
    return ego


def _run(ego, hour, timestamps):
    fake_now = SimpleNamespace(hour=hour, minute=30)
    fake_datetime = SimpleNamespace(now=lambda: fake_now)
    with patch("core.self_model.datetime", fake_datetime), patch("builtins.print"):
        for ts in timestamps:
            with patch("core.self_model.time.time", return_value=ts):
                ego.apply_circadian_rhythm()


class CircadianDtScalingTests(unittest.TestCase):
    def test_first_call_only_initializes_clock(self):
        ego = _ego()
        _run(ego, 0, [START])
        self.assertEqual(ego.fatigue, 0.3)
        self.assertEqual(ego.mood, 0.0)
        self.assertEqual(ego.curiosity, 0.5)
        self.assertEqual(ego._last_circadian_time, START)

    def test_call_frequency_does_not_change_night_drift(self):
        # One call per hour vs. one call every 30s across the same hour.
        sparse = _ego()
        _run(sparse, 0, [START, START + 3600])
        dense = _ego()
        _run(dense, 0, [START + 30 * i for i in range(121)])

        for name in ("fatigue", "mood", "curiosity"):
            self.assertAlmostEqual(getattr(sparse, name), getattr(dense, name), places=9)
        self.assertAlmostEqual(dense.fatigue, 0.32, places=9)
        self.assertAlmostEqual(dense.mood, -0.01, places=9)
        self.assertAlmostEqual(dense.curiosity, 0.45, places=9)

    def test_burst_of_interactions_barely_moves_state(self):
        ego = _ego()
        _run(ego, 0, [START + 0.01 * i for i in range(500)])
        self.assertLess(ego.fatigue - 0.3, 1e-4)
        self.assertLess(0.5 - ego.curiosity, 1e-4)

    def test_post_lunch_dip_never_lowers_fatigue(self):
        ego = _ego(fatigue=0.9, fatigue_critical=0.5)
        _run(ego, 14, [START, START + 3600])
        self.assertEqual(ego.fatigue, 0.9)

    def test_sleep_deprivation_stress_is_rate_based(self):
        ego = _ego(last_slept_time=START - 2.5 * 24 * 3600)
        # 50 minutes of 30s ticks after the clock is initialized.
        _run(ego, 10, [START + 30 * i for i in range(101)])
        self.assertEqual(ego.days_without_sleep, 2)
        self.assertAlmostEqual(ego.stress, 0.1 + 0.05 * 2 * (50 / 60), places=9)
        self.assertLess(ego.stress, 0.95)

    def test_elapsed_time_is_capped_at_one_hour(self):
        ego = _ego()
        _run(ego, 0, [START, START + 10 * 3600])
        self.assertAlmostEqual(ego.curiosity, 0.45, places=9)

    def test_clock_going_backwards_is_ignored(self):
        ego = _ego()
        _run(ego, 0, [START, START - 3600])
        self.assertEqual(ego.curiosity, 0.5)


if __name__ == "__main__":
    unittest.main()
