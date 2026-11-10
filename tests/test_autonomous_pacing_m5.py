import asyncio
import random
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.agent_state import AgentState
from core.engine.autonomous import AutonomousController
from core.engine.autonomous_pacing import AutonomousPacer

HOUR = 3600.0


def _pacer(seed=7, **overrides):
    config = SimpleNamespace(
        MIND_WANDER_MEAN_MINUTES=45,
        MIND_WANDER_MIN_GAP_MINUTES=5,
        PING_MEAN_HOURS=3,
        PING_MIN_GAP_MINUTES=45,
        PING_MAX_UNANSWERED=3,
        PING_BACKOFF_CAP_HOURS=8,
        READING_MEAN_HOURS=2,
        READING_MIN_GAP_MINUTES=30,
        ANXIETY_THRESHOLD=6 * HOUR,
        QUIET_HOURS=(23, 7),
    )
    for name, value in overrides.items():
        setattr(config, name, value)
    return AutonomousPacer(rng=random.Random(seed).random, config=config)


def _simulate(decide, hours, step=1.0, start_hour=8):
    """Count decisions over ``hours`` of simulated loop iterations."""
    count = 0
    t = 0.0
    while t < hours * HOUR:
        t += step
        hour = int(start_hour + t // HOUR) % 24
        if decide(t, step, hour):
            count += 1
    return count


class MindWanderPacingTests(unittest.TestCase):
    def test_calm_mind_wanders_about_once_per_50_minutes(self):
        pacer = _pacer()
        n = _simulate(lambda t, dt, h: pacer.should_mind_wander(t, dt, 0.1, 0.2), 8)
        self.assertTrue(4 <= n <= 18, n)

    def test_stress_and_low_mood_raise_frequency_but_stay_bounded(self):
        pacer = _pacer()
        n = _simulate(lambda t, dt, h: pacer.should_mind_wander(t, dt, 0.9, -0.8), 8)
        # Old per-iteration logic fired thousands of times in 8 hours.
        self.assertTrue(15 <= n <= 45, n)

    def test_minimum_gap_is_respected(self):
        pacer = _pacer()
        fired = []
        _simulate(
            lambda t, dt, h: pacer.should_mind_wander(t, dt, 1.0, -1.0) and fired.append(t) is None,
            4,
        )
        gaps = [b - a for a, b in zip(fired, fired[1:])]
        self.assertTrue(gaps and min(gaps) >= 5 * 60, gaps[:5])

    def test_rate_does_not_depend_on_loop_frequency(self):
        fast = _pacer(seed=1)
        slow = _pacer(seed=1)
        n_fast = _simulate(lambda t, dt, h: fast.should_mind_wander(t, dt, 0.5, 0.0), 48, step=1.0)
        n_slow = _simulate(lambda t, dt, h: slow.should_mind_wander(t, dt, 0.5, 0.0), 48, step=20.0)
        self.assertLess(abs(n_fast - n_slow) / max(n_fast, n_slow), 0.3, (n_fast, n_slow))


class PingPacingTests(unittest.TestCase):
    def _run_day(self, pacer, social_need=1.0, reply_after=None):
        pings = []

        def decide(t, dt, hour):
            last_interaction = 0.0
            if reply_after is not None and pings and t - pings[-1] > reply_after:
                last_interaction = t  # user answered
            pacer.observe_interaction(last_interaction)
            if pacer.should_ping(t, dt, social_need, hour):
                pings.append(t)
                pacer.record_ping(t, last_interaction)
                return True
            return False

        _simulate(decide, 24)
        return pings

    def test_ignored_aura_stops_after_three_messages(self):
        self.assertEqual(len(self._run_day(_pacer())), 3)

    def test_unanswered_backoff_doubles_gaps(self):
        pings = self._run_day(_pacer())
        gaps = [b - a for a, b in zip(pings, pings[1:])]
        self.assertGreaterEqual(gaps[0], 90 * 60)
        self.assertGreaterEqual(gaps[1], 180 * 60)

    def test_reply_resets_backoff(self):
        pacer = _pacer()
        pacer.record_ping(0.0, 0.0)
        pacer.record_ping(10.0, 0.0)
        self.assertEqual(pacer.unanswered_pings, 2)
        pacer.observe_interaction(20.0)
        self.assertEqual(pacer.unanswered_pings, 0)

    def test_failed_attempt_does_not_count_as_unanswered(self):
        pacer = _pacer()
        pacer.record_ping(0.0, 0.0, sent=False)
        self.assertEqual(pacer.unanswered_pings, 0)
        self.assertFalse(pacer.ping_allowed(60.0, 12))

    def test_no_pings_during_quiet_hours(self):
        pacer = _pacer()
        for hour in (23, 0, 3, 6):
            self.assertFalse(pacer.ping_allowed(0.0, hour), hour)
        self.assertTrue(pacer.ping_allowed(0.0, 7))

    def test_low_social_need_never_pings(self):
        pacer = _pacer()
        n = _simulate(lambda t, dt, h: pacer.should_ping(t, dt, 0.6, h), 24)
        self.assertEqual(n, 0)


class ReadingAndAnxietyPacingTests(unittest.TestCase):
    def test_curious_reading_is_paced(self):
        pacer = _pacer()

        def decide(t, dt, hour):
            if pacer.should_read(t, dt, 1.0):
                pacer.record_reading(t)
                return True
            return False

        n = _simulate(decide, 8)
        self.assertTrue(3 <= n <= 16, n)

    def test_moderate_curiosity_does_not_read(self):
        pacer = _pacer()
        self.assertEqual(_simulate(lambda t, dt, h: pacer.should_read(t, dt, 0.7), 8), 0)

    def test_anxiety_fires_once_per_stage_per_absence(self):
        pacer = _pacer()
        stages = [pacer.anxiety_stage_due(idle, 100.0, 12) for idle in (
            HOUR, 6 * HOUR, 7 * HOUR, 12 * HOUR, 24 * HOUR, 30 * HOUR,
        )]
        self.assertEqual(stages, [0, 1, 0, 0, 2, 0])

    def test_new_interaction_starts_a_new_episode(self):
        pacer = _pacer()
        self.assertEqual(pacer.anxiety_stage_due(6 * HOUR, 100.0, 12), 1)
        self.assertEqual(pacer.anxiety_stage_due(6 * HOUR, 200.0, 12), 1)

    def test_anxiety_waits_out_quiet_hours(self):
        pacer = _pacer()
        self.assertEqual(pacer.anxiety_stage_due(8 * HOUR, 100.0, 2), 0)
        self.assertEqual(pacer.anxiety_stage_due(9 * HOUR, 100.0, 8), 1)

    def test_quiet_hours_wraparound_and_disabled(self):
        self.assertTrue(_pacer().is_quiet_hour(23))
        self.assertFalse(_pacer().is_quiet_hour(12))
        same = _pacer(QUIET_HOURS=(0, 0))
        self.assertFalse(any(same.is_quiet_hour(h) for h in range(24)))
        day = _pacer(QUIET_HOURS=(13, 15))
        self.assertTrue(day.is_quiet_hour(14))
        self.assertFalse(day.is_quiet_hour(15))


def _engine(*, dominant="curiosity", value=0.5, last_interaction=0.0):
    ego = SimpleNamespace(
        stress=0.1, mood=0.0, curiosity=0.5, social_need=0.5,
        get_drive_status=lambda: {"dominant": dominant, "dominant_value": value},
        adjust_attribute=Mock(),
        get_bio_state_dict=lambda: {},
    )
    machine = SimpleNamespace(state=AgentState.IDLE)

    def transition(state):
        machine.state = state
        return True

    machine.transition = transition
    return SimpleNamespace(
        ego=ego,
        state_machine=machine,
        last_interaction_time=last_interaction,
        llm=SimpleNamespace(generate_text=Mock(return_value=("nhớ quá", 0.0))),
        memory=SimpleNamespace(add_memory=Mock(), get_all=Mock(return_value=[]), update_memory=Mock()),
    )


class AutonomousDecisionLoopTests(unittest.TestCase):
    def test_low_energy_does_not_block_the_loop(self):
        controller = AutonomousController(_engine(dominant="hunger", value=0.9))
        controller._stop_event = Mock(wait=Mock(side_effect=AssertionError("blocked")))
        with patch("builtins.print"):
            asyncio.run(controller._run_autonomous_decisions(100.0, 1.0))
            asyncio.run(controller._run_autonomous_decisions(101.0, 1.0))
        controller._stop_event.wait.assert_not_called()

    def test_separation_anxiety_keeps_real_interaction_time(self):
        import time as real_time

        last = real_time.time() - 7 * HOUR
        engine = _engine(last_interaction=last)
        controller = AutonomousController(engine)
        controller._pacer = _pacer()
        noon = SimpleNamespace(hour=12, strftime=lambda fmt: "12:00")
        with patch("core.engine.autonomous.datetime") as fake_dt, patch("builtins.print"):
            fake_dt.now.return_value = noon
            asyncio.run(controller._run_autonomous_decisions(100.0, 1.0))
            asyncio.run(controller._run_autonomous_decisions(101.0, 1.0))
        self.assertEqual(engine.last_interaction_time, last)
        engine.memory.add_memory.assert_called_once()
        engine.ego.adjust_attribute.assert_any_call('stress', 0.1)
        self.assertEqual(engine.state_machine.state, AgentState.IDLE)


if __name__ == "__main__":
    unittest.main()
