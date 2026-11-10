import datetime as dt
import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.engine import sleep_cycle
from core.engine.memory_ops import MemoryOperationsController


def _ts(day, hour, minute=0):
    return dt.datetime(2026, 10, 19 + day, hour, minute).timestamp()


class _Rng:
    def uniform(self, low, high):
        return (low + high) / 2

    def gauss(self, mu, sigma):
        return 0.0


def _ego(**kw):
    ego = SimpleNamespace(lock=threading.Lock(), fatigue=0.0, asleep_until=0.0,
                          asleep_since=0.0, sleep_intervals=[])
    for key, value in kw.items():
        setattr(ego, key, value)
    return ego


class ScheduleTests(unittest.TestCase):
    def test_night_sleep_ends_around_seven(self):
        onset = _ts(0, 23)
        wake = sleep_cycle.wake_time(onset, nap=False, rng=_Rng())
        self.assertEqual(dt.datetime.fromtimestamp(wake).hour, 7)
        self.assertAlmostEqual((wake - onset) / 3600, 8.0)

    def test_late_night_still_gets_minimum_sleep(self):
        onset = _ts(1, 3, 30)
        wake = sleep_cycle.wake_time(onset, nap=False, rng=_Rng())
        self.assertAlmostEqual((wake - onset) / 3600, 6.0)

    def test_nap_is_short(self):
        onset = _ts(0, 14)
        wake = sleep_cycle.wake_time(onset, nap=True, rng=_Rng())
        self.assertAlmostEqual((wake - onset) / 60, 65.0)

    def test_bedtime_pressure_only_at_night(self):
        always = lambda: 0.0  # noqa: E731
        never = lambda: 0.999999  # noqa: E731
        self.assertFalse(sleep_cycle.bedtime_onset_due(_ts(0, 15), 1.0, 600, rng=always))
        self.assertTrue(sleep_cycle.bedtime_onset_due(_ts(0, 23), 0.2, 600, rng=always))
        self.assertFalse(sleep_cycle.bedtime_onset_due(_ts(0, 23), 0.2, 600, rng=never))
        self.assertFalse(sleep_cycle.bedtime_onset_due(_ts(0, 23), 0.2, 0.0, rng=always))


class SleepStateTests(unittest.TestCase):
    def test_maintenance_runs_once_per_night_but_naps_do_not_block_it(self):
        ego = _ego()
        maintenance = Mock()
        sleep_cycle.begin_sleep(ego, _ts(0, 14), nap=True, run_maintenance=maintenance, rng=_Rng())
        sleep_cycle.begin_sleep(ego, _ts(0, 17), nap=False, run_maintenance=maintenance, rng=_Rng())
        self.assertEqual(maintenance.call_count, 2)  # the night is not swallowed by the nap
        sleep_cycle.wake_up(ego, _ts(0, 19), forced=True)
        sleep_cycle.begin_sleep(ego, _ts(0, 20), nap=False, run_maintenance=maintenance, rng=_Rng())
        self.assertEqual(maintenance.call_count, 2)  # dozing off again the same night

    def test_forced_wake_keeps_part_of_the_fatigue_and_truncates_the_interval(self):
        ego = _ego()
        onset = _ts(0, 23)
        until = sleep_cycle.begin_sleep(ego, onset, nap=False, run_maintenance=Mock(), rng=_Rng())
        self.assertTrue(sleep_cycle.is_asleep(ego, onset + 60))
        woken = onset + 2 * 3600
        sleep_cycle.wake_up(ego, woken, forced=True)
        self.assertFalse(sleep_cycle.is_asleep(ego, woken))
        self.assertAlmostEqual(ego.fatigue, 0.5 * (until - woken) / (until - onset))
        self.assertEqual(ego.sleep_intervals[-1], (onset, woken))
        self.assertEqual(ego.just_woken_at, woken)

    def test_hours_asleep_do_not_count_as_absence(self):
        intervals = [(_ts(0, 23), _ts(1, 7))]
        awake = sleep_cycle.awake_seconds_between(_ts(0, 20), _ts(1, 9), intervals)
        self.assertAlmostEqual(awake / 3600, 5.0)

    def test_works_with_lockless_ego_doubles(self):
        ego = SimpleNamespace(fatigue=0.0)
        sleep_cycle.begin_sleep(ego, _ts(0, 23), nap=False, run_maintenance=Mock(), rng=_Rng())
        self.assertTrue(sleep_cycle.is_asleep(ego, _ts(0, 23, 30)))


class MoodHomeostasisTests(unittest.TestCase):
    def test_mood_returns_to_set_point_faster_asleep(self):
        awake = sleep_cycle.relax_mood(-0.8, 8 * 3600, asleep=False)
        asleep = sleep_cycle.relax_mood(-0.8, 8 * 3600, asleep=True)
        self.assertGreater(awake, -0.8)
        self.assertGreater(asleep, awake)
        self.assertLess(asleep, sleep_cycle.MOOD_SET_POINT)

    def test_loneliness_lowers_the_set_point(self):
        self.assertAlmostEqual(sleep_cycle.mood_set_point(0.5), sleep_cycle.MOOD_SET_POINT)
        self.assertLess(sleep_cycle.mood_set_point(1.0), 0.0)
        lonely = sleep_cycle.relax_mood(0.1, 48 * 3600, asleep=False, social_need=1.0)
        self.assertLess(lonely, 0.0)


class SelfModelSleepTests(unittest.TestCase):
    def _model(self):
        from tests.test_self_model_load_m23 import _new_self_model

        model = _new_self_model()
        model.mood_anchor = None
        return model

    def test_asleep_recovers_fatigue_and_feels_no_loneliness(self):
        model = self._model()
        model.fatigue = 0.8
        model.social_need = 0.5
        model.asleep_until = 2_000_000_000.0
        with patch("core.self_model.time.time", return_value=1_000_000.0), patch("builtins.print"):
            model.apply_biological_decay(2 * 3600, idle_time=10 * 3600)
        self.assertLess(model.fatigue, 0.8 * 0.4)
        self.assertEqual(model.social_need, 0.5)

    def test_awake_fatigue_and_loneliness_still_grow(self):
        model = self._model()
        model.fatigue = 0.2
        model.social_need = 0.5
        with patch("core.self_model.time.time", return_value=1_000_000.0), patch("builtins.print"):
            model.apply_biological_decay(2 * 3600, idle_time=10 * 3600)
        self.assertGreater(model.fatigue, 0.2)
        self.assertGreater(model.social_need, 0.5)


class IdentityOncePerNightTests(unittest.TestCase):
    def test_nap_after_a_night_reflection_does_not_reflect_again(self):
        ego = SimpleNamespace(
            lock=threading.Lock(), evolved_insight="", actionable_lessons=[],
            last_identity_reflection=1_000_000.0,
        )
        controller = object.__new__(MemoryOperationsController)
        controller.engine = SimpleNamespace(
            ego=ego,
            stm_lock=threading.Lock(),
            short_term_buffer=["a", "b", "c", "d"],
            llm=SimpleNamespace(generate_text=Mock(return_value=(json.dumps({
                "insight": "x" * 20, "actionable_lessons": [], "value_updates": [],
            }), 0.0))),
        )
        with patch("core.engine.memory_ops.time.time", return_value=1_000_000.0 + 8 * 3600):
            controller._identity_evolution_phase()
        controller.engine.llm.generate_text.assert_not_called()


if __name__ == "__main__":
    unittest.main()
