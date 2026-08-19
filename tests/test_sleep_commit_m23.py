import json
import math
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.engine.memory_ops import (
    MemoryOperationsController,
    SleepMaintenanceError,
)
from core.event_journal import (
    EventJournal,
    JournalContext,
    activate_journal_context,
    reset_journal_context,
)
from core.self_model import SelfModel


_SLEEP_FIELDS = (
    "stress",
    "fatigue",
    "energy",
    "atp_level",
    "last_slept_time",
    "days_without_sleep",
    "_sleep_warning_cooldown",
)


def _make_ego(*, save_state=None):
    ego = SimpleNamespace(
        lock=threading.Lock(),
        stress=0.8,
        fatigue=0.9,
        energy=0.1,
        atp_level=0.2,
        last_slept_time=100.0,
        days_without_sleep=3,
        _sleep_warning_cooldown=True,
        mood=0.4,
        social_need=0.2,
        curiosity=0.3,
        fatigue_critical=1.0,
        bio_controller=SimpleNamespace(sensitivities={"stress": 1.0}),
        calculate_chronic_mood=Mock(return_value=0.2),
        reroll_thresholds=Mock(),
        check_integrity=Mock(),
        save_state=save_state or Mock(),
    )

    def commit_sleep_state(completed_at):
        before = _sleep_snapshot(ego)
        with ego.lock:
            ego.stress = max(0.0, ego.stress - 0.3)
            ego.fatigue = 0.0
            ego.energy = 1.0
            ego.atp_level = 1.0
            ego.last_slept_time = completed_at
            ego.days_without_sleep = 0
            ego._sleep_warning_cooldown = False
        try:
            ego.save_state()
        except BaseException:
            with ego.lock:
                for field, value in before.items():
                    setattr(ego, field, value)
            raise

    ego.commit_sleep_state = commit_sleep_state
    return ego


def _make_controller(*, ego=None):
    ego = ego or _make_ego()
    memory = SimpleNamespace(
        get_all=Mock(return_value=[]),
        enforce_garbage_collection=Mock(),
    )
    controller = object.__new__(MemoryOperationsController)
    controller.engine = SimpleNamespace(ego=ego, memory=memory)
    controller.slm_trainer = None
    for phase in (
        "_dream_consolidation_phase",
        "_decay_phase",
        "_guilt_reflection_phase",
        "_cognitive_reappraisal_phase",
        "_identity_evolution_phase",
        "_tool_workshop_phase",
        "_calibration_phase",
        "_belief_evolution_phase",
    ):
        setattr(controller, phase, Mock())
    return controller


def _sleep_snapshot(ego):
    return {field: getattr(ego, field) for field in _SLEEP_FIELDS}


def _new_self_model():
    with patch.object(SelfModel, "load_identity"), patch.object(
        SelfModel,
        "reroll_thresholds",
    ), patch.object(SelfModel, "_check_environment"):
        return SelfModel(memory_manager=None)


class SleepSagaTests(unittest.TestCase):
    def test_decay_failure_restores_homeostasis_and_stops_later_phases(self):
        ego = _make_ego()
        controller = _make_controller(ego=ego)
        before = _sleep_snapshot(ego)

        def fail_decay(*_args):
            # The saga boundary restores even an accidental critical-phase
            # mutation, not only the planned sleep reset.
            ego.energy = 0.77
            raise OSError("storage failed")

        controller._decay_phase.side_effect = fail_decay

        with patch("builtins.print"):
            with self.assertRaises(SleepMaintenanceError) as raised:
                controller.sleep()

        self.assertEqual(raised.exception.phase, "decay")
        self.assertFalse(raised.exception.sleep_committed)
        self.assertEqual(_sleep_snapshot(ego), before)
        ego.save_state.assert_not_called()
        controller._guilt_reflection_phase.assert_not_called()
        controller._belief_evolution_phase.assert_not_called()
        controller.engine.memory.enforce_garbage_collection.assert_not_called()

    def test_save_failure_restores_exact_ram_and_stops_enrichment(self):
        save_state = Mock(side_effect=OSError("disk full"))
        ego = _make_ego(save_state=save_state)
        controller = _make_controller(ego=ego)
        before = _sleep_snapshot(ego)

        with patch("core.engine.memory_ops.time.time", return_value=5_000.0), patch(
            "builtins.print"
        ):
            with self.assertRaises(SleepMaintenanceError) as raised:
                controller.sleep()

        self.assertEqual(raised.exception.phase, "sleep_state_commit")
        self.assertFalse(raised.exception.sleep_committed)
        self.assertEqual(_sleep_snapshot(ego), before)
        save_state.assert_called_once_with()
        controller._guilt_reflection_phase.assert_not_called()

    def test_failed_commit_retry_applies_homeostasis_once(self):
        save_state = Mock(side_effect=[OSError("first attempt"), None])
        ego = _make_ego(save_state=save_state)
        controller = _make_controller(ego=ego)

        with patch(
            "core.engine.memory_ops.time.time",
            side_effect=[5_000.0, 6_000.0],
        ), patch("builtins.print"):
            with self.assertRaises(SleepMaintenanceError):
                controller.sleep()
            controller.sleep()

        self.assertEqual(save_state.call_count, 2)
        self.assertAlmostEqual(ego.stress, 0.5)
        self.assertEqual(ego.fatigue, 0.0)
        self.assertEqual(ego.energy, 1.0)
        self.assertEqual(ego.atp_level, 1.0)
        self.assertEqual(ego.last_slept_time, 6_000.0)
        self.assertEqual(ego.days_without_sleep, 0)
        self.assertFalse(ego._sleep_warning_cooldown)
        self.assertTrue(controller.last_sleep_outcome.sleep_committed)

    def test_post_commit_failure_is_degraded_and_later_phases_continue(self):
        controller = _make_controller()
        controller._guilt_reflection_phase.side_effect = RuntimeError("bad LLM")

        with patch("core.engine.memory_ops.time.time", return_value=5_000.0), patch(
            "core.logger.get_logger",
            return_value=Mock(),
        ), patch("builtins.print"):
            result = controller.sleep()

        self.assertIsNone(result)
        self.assertTrue(controller.last_sleep_outcome.sleep_committed)
        self.assertEqual(
            [failure.phase for failure in controller.last_sleep_outcome.degraded_phases],
            ["guilt_reflection"],
        )
        controller._cognitive_reappraisal_phase.assert_called_once_with()
        controller._belief_evolution_phase.assert_called_once_with()
        controller.engine.memory.enforce_garbage_collection.assert_called_once_with()

    def test_degraded_sleep_writes_safe_success_journal_metadata(self):
        controller = _make_controller()
        controller._guilt_reflection_phase.side_effect = RuntimeError(
            "secret exception content"
        )

        with tempfile.TemporaryDirectory() as directory:
            journal = EventJournal(Path(directory) / "journal")
            token = activate_journal_context(
                journal,
                JournalContext(source="test"),
            )
            try:
                with patch(
                    "core.engine.memory_ops.time.time",
                    return_value=5_000.0,
                ), patch("core.logger.get_logger", return_value=Mock()), patch(
                    "builtins.print"
                ):
                    controller.sleep()
            finally:
                reset_journal_context(token)

            events = list(journal.iter_events())

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "maintenance.sleep")
        self.assertEqual(events[0].outcome, "succeeded")
        self.assertEqual(
            dict(events[0].payload),
            {"sleep_committed": True, "degraded_phase_count": 1},
        )

    def test_post_commit_observability_failures_cannot_fail_sleep(self):
        controller = _make_controller()
        controller._guilt_reflection_phase.side_effect = RuntimeError(
            "secret exception content"
        )

        with patch("core.engine.memory_ops.time.time", return_value=5_000.0), patch(
            "core.logger.get_logger",
            side_effect=RuntimeError("logger unavailable"),
        ), patch(
            "core.event_journal.record_current_event",
            side_effect=RuntimeError("journal unavailable"),
        ), patch("builtins.print"):
            result = controller.sleep()

        self.assertIsNone(result)
        self.assertTrue(controller.last_sleep_outcome.sleep_committed)
        self.assertEqual(
            [failure.phase for failure in controller.last_sleep_outcome.degraded_phases],
            ["guilt_reflection"],
        )
        controller._belief_evolution_phase.assert_called_once_with()


class SleepClockPersistenceTests(unittest.TestCase):
    def test_sleep_clocks_round_trip(self):
        source = _new_self_model()
        source.last_slept_time = 12_345.25
        source.days_without_sleep = 4
        source._sleep_warning_cooldown = True

        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "ego.json"
            source.save_state(str(state_path))
            persisted = json.loads(state_path.read_text(encoding="utf-8"))

            target = _new_self_model()
            target.last_slept_time = 999.0
            target.days_without_sleep = 0
            target._sleep_warning_cooldown = False
            target.load_state(str(state_path))

        self.assertEqual(persisted["last_slept_time"], 12_345.25)
        self.assertEqual(persisted["days_without_sleep"], 4)
        self.assertIs(persisted["_sleep_warning_cooldown"], True)
        self.assertEqual(target.last_slept_time, 12_345.25)
        self.assertEqual(target.days_without_sleep, 4)
        self.assertIs(target._sleep_warning_cooldown, True)

    def test_invalid_or_legacy_clock_keeps_backward_compatible_defaults(self):
        invalid_states = (
            {
                "last_slept_time": math.nan,
                "days_without_sleep": 2,
                "_sleep_warning_cooldown": True,
            },
            {
                "last_slept_time": 123.0,
                "days_without_sleep": True,
                "_sleep_warning_cooldown": False,
            },
            {
                "last_slept_time": 123.0,
                "days_without_sleep": 2,
                "_sleep_warning_cooldown": 1,
            },
            {"last_slept_time": 123.0},
            {"stress": 0.2},
        )
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "ego.json"
            for state in invalid_states:
                with self.subTest(state=state):
                    state_path.write_text(json.dumps(state), encoding="utf-8")
                    target = _new_self_model()
                    target.last_slept_time = 999.0
                    target.days_without_sleep = 7
                    target._sleep_warning_cooldown = True
                    target.load_state(str(state_path))
                    self.assertEqual(target.last_slept_time, 999.0)
                    self.assertEqual(target.days_without_sleep, 7)
                    self.assertIs(target._sleep_warning_cooldown, True)

    def test_atomic_sleep_write_failure_restores_production_self_model(self):
        model = _new_self_model()
        model.stress = 0.8
        model.fatigue = 0.9
        model.energy = 0.1
        model.atp_level = 0.2
        model.last_slept_time = 100.0
        model.days_without_sleep = 3
        model._sleep_warning_cooldown = True
        before = _sleep_snapshot(model)

        with patch("core.utils.atomic_write_json", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                model.commit_sleep_state(5_000.0)

        self.assertEqual(_sleep_snapshot(model), before)

    def test_save_rejects_non_finite_sleep_clock(self):
        model = _new_self_model()
        model.last_slept_time = math.inf
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "ego.json"
            with self.assertRaises(ValueError):
                model.save_state(str(state_path))
            self.assertFalse(state_path.exists())


if __name__ == "__main__":
    unittest.main()
