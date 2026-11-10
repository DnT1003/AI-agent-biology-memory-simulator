import math
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.engine import dopamine
from core.engine.autonomous import AutonomousController
from core.self_model import SelfModel, _validated_persisted_state


class PredictionErrorTests(unittest.TestCase):
    def test_repeated_reward_habituates(self):
        expectations = {}
        deltas = []
        for _ in range(30):
            delta, expectations = dopamine.prediction_error(expectations, "reading", 0.4)
            deltas.append(delta)
        self.assertAlmostEqual(deltas[0], 0.4)
        self.assertLess(deltas[-1], 0.1)
        self.assertTrue(all(a >= b for a, b in zip(deltas, deltas[1:])))

    def test_missing_expected_reward_is_a_dip(self):
        expectations = {"user_message": 0.5}
        delta, _ = dopamine.prediction_error(expectations, "user_message", 0.0)
        self.assertAlmostEqual(delta, -0.5)
        self.assertLess(dopamine.burst(0.5, delta, 1.0), 0.5)

    def test_unknown_event_is_rejected(self):
        with self.assertRaises(ValueError):
            dopamine.prediction_error({}, "lottery", 1.0)

    def test_blunted_receptors_weaken_bursts(self):
        strong = dopamine.burst(0.5, 0.5, 1.0) - 0.5
        weak = dopamine.burst(0.5, 0.5, 0.3) - 0.5
        self.assertAlmostEqual(weak, strong * 0.3)


class DopamineDynamicsTests(unittest.TestCase):
    def test_burst_fades_with_15_minute_time_constant(self):
        level, baseline, _ = dopamine.relax(0.8, 0.5, 1.0, 0.0, 15 * 60)
        self.assertAlmostEqual(level - baseline, 0.3 * math.exp(-1), places=2)

    def test_baseline_follows_mood_over_hours(self):
        _, baseline, _ = dopamine.relax(0.5, 0.5, 1.0, -1.0, 48 * 3600)
        self.assertAlmostEqual(baseline, 0.3, places=2)

    def test_dynamics_do_not_depend_on_step_size(self):
        coarse = dopamine.relax(0.9, 0.5, 1.0, 0.5, 3600)
        fine = (0.9, 0.5, 1.0)
        for _ in range(120):
            fine = dopamine.relax(*fine, 0.5, 30)
        self.assertAlmostEqual(coarse[0], fine[0], places=2)
        self.assertAlmostEqual(coarse[1], fine[1], places=3)

    def test_sustained_high_dopamine_builds_tolerance_then_recovers(self):
        receptors = 1.0
        for _ in range(10 * 120):  # 10 hours pinned high
            _, _, receptors = dopamine.relax(0.95, 0.95, receptors, 0.0, 30)
        self.assertLess(receptors, 0.85)
        blunted = receptors
        for _ in range(24 * 120):  # a calm day
            _, _, receptors = dopamine.relax(0.5, 0.5, receptors, 0.0, 30)
        self.assertGreater(receptors, blunted)

    def test_motivation_range(self):
        self.assertEqual(dopamine.motivation(0.0), 0.5)
        self.assertEqual(dopamine.motivation(1.0), 1.5)


def _ego():
    ego = SelfModel.__new__(SelfModel)
    ego.lock = threading.Lock()
    ego.mood = 0.0
    ego.dopamine_level = 0.5
    ego.dopamine_baseline = 0.5
    ego.dopamine_receptors = 1.0
    ego.reward_expectations = {}
    ego._last_user_contact_at = None
    return ego


class SelfModelRewardTests(unittest.TestCase):
    def test_register_reward_raises_dopamine_and_nudges_mood(self):
        ego = _ego()
        delta = ego.register_reward("new_book", 0.6)
        self.assertAlmostEqual(delta, 0.6)
        self.assertAlmostEqual(ego.dopamine_level, 0.5 + 0.3 * 0.6)
        self.assertAlmostEqual(ego.mood, 0.05 * 0.6)
        self.assertAlmostEqual(ego.reward_expectations["new_book"], 0.06)

    def test_reunion_bonus_only_after_long_absence(self):
        ego = _ego()
        ego.register_user_contact(0.5, now=1_000.0)
        ego.register_user_contact(0.5, now=1_600.0)  # 10 minutes later
        self.assertNotIn("reunion", ego.reward_expectations)
        ego.register_user_contact(0.5, now=1_600.0 + 6 * 3600)
        self.assertIn("reunion", ego.reward_expectations)

    def test_reward_state_validates_on_load(self):
        state = _validated_persisted_state({
            "dopamine_baseline": 0.4,
            "reward_expectations": {"reading": 0.2},
        })
        self.assertEqual(state["reward_expectations"], {"reading": 0.2})
        with self.assertRaises(ValueError):
            _validated_persisted_state({"reward_expectations": {"lottery": 0.2}})
        with self.assertRaises(ValueError):
            _validated_persisted_state({"reward_expectations": {"reading": 2.0}})


class AutonomousRewardTests(unittest.TestCase):
    def _controller(self):
        ego = SimpleNamespace(register_reward=Mock(), adjust_attribute=Mock())
        engine = SimpleNamespace(ego=ego, last_interaction_time=0.0)
        return AutonomousController(engine), ego

    def test_second_unanswered_message_registers_ignored(self):
        controller, ego = self._controller()
        controller._record_ping_attempt(True)
        ego.register_reward.assert_not_called()
        controller._record_ping_attempt(True)
        ego.register_reward.assert_called_once_with("ping_ignored", -0.4)

    def test_failed_attempt_is_not_ignored(self):
        controller, ego = self._controller()
        controller._record_ping_attempt(True)
        controller._record_ping_attempt(False)
        ego.register_reward.assert_not_called()


if __name__ == "__main__":
    unittest.main()
