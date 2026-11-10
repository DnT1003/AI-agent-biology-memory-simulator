import math
import json
import logging
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

logging.disable(logging.CRITICAL)
from config import Config
from core.agent_state import AgentState, StateMachine
from core.engine.autonomous import AutonomousController
from core.engine.cognitive_engine import CognitiveEngine
from core.engine.memory_ops import MemoryOperationsController
from core.memory import MemoryTrace, MemoryType
from components.vector_store import VectorStore
from core.self_model import SelfModel
logging.disable(logging.NOTSET)


class _RecordingTrace:
    def __init__(self):
        self.elapsed_days = None
        self.stress_level = None
        self.created_at = 1_000.0
        self.last_decayed_at = 1_000.0

    def decay(self, *, stress_level, elapsed_days):
        self.stress_level = stress_level
        self.elapsed_days = elapsed_days


class _FakeEgo:
    """A SelfModel-shaped fake whose public methods own a plain Lock."""

    def __init__(self):
        self.lock = threading.Lock()
        self.fatigue = 0.2
        self.stress = 0.3
        self.energy = 0.5
        self.atp_level = 0.5
        self.curiosity = 0.5
        self.biological_calls = 0
        self.circadian_calls = 0
        self.save_calls = 0

    def apply_biological_decay(self, dt, idle_seconds):
        with self.lock:
            self.biological_calls += 1

    def apply_circadian_rhythm(self):
        with self.lock:
            self.circadian_calls += 1

    def apply_circadian_rhythm_deferred(self):
        self.apply_circadian_rhythm()
        return False

    def adjust_attribute(self, name, delta, min_val=0.0, max_val=1.0):
        with self.lock:
            value = getattr(self, name)
            setattr(self, name, max(min_val, min(max_val, value + delta)))

    def save_state(self):
        with self.lock:
            self.save_calls += 1


class _FakeMemory:
    def __init__(self, ego, traces=None):
        self.ego = ego
        self.traces = list(traces or [])
        self.updated = []
        self.gc_calls = 0

    def _assert_no_ego_lock(self):
        if self.ego.lock.locked():
            raise AssertionError("memory operation started while ego.lock was held")

    def get_all(self):
        self._assert_no_ego_lock()
        return list(self.traces)

    def update_memory(self, trace):
        self._assert_no_ego_lock()
        self.updated.append(trace)

    def enforce_garbage_collection(self):
        self._assert_no_ego_lock()
        self.gc_calls += 1


def _make_tick_engine(traces=None, state=AgentState.IDLE):
    engine = CognitiveEngine.__new__(CognitiveEngine)
    engine.ego = _FakeEgo()
    engine.memory = _FakeMemory(engine.ego, traces)
    engine.state_machine = SimpleNamespace(state=state)
    engine.last_interaction_time = time.time()
    engine._dump_mind_state = lambda: None
    return engine


class RuntimeLockingTests(unittest.TestCase):
    def _run_with_timeout(self, target, timeout=1.0):
        errors = []
        completed = threading.Event()

        def runner():
            try:
                target()
            except BaseException as exc:  # propagate worker assertions to unittest
                errors.append(exc)
            finally:
                completed.set()

        worker = threading.Thread(target=runner, daemon=True)
        worker.start()
        self.assertTrue(completed.wait(timeout), "worker deadlocked")
        if errors:
            raise errors[0]

    def test_cognitive_tick_does_not_nest_plain_ego_lock(self):
        engine = _make_tick_engine(state=AgentState.THINKING)
        with patch("core.engine.cognitive_engine.os.path.exists", return_value=False):
            self._run_with_timeout(lambda: engine.cognitive_tick(30.0))

        self.assertEqual(engine.ego.biological_calls, 1)
        self.assertEqual(engine.ego.circadian_calls, 1)
        self.assertEqual(engine.memory.gc_calls, 1)

    def test_cognitive_tick_is_terminal_after_shutdown(self):
        engine = _make_tick_engine(state=AgentState.SHUTDOWN)

        self.assertFalse(engine.cognitive_tick(30.0))
        self.assertEqual(engine.ego.biological_calls, 0)
        self.assertEqual(engine.memory.gc_calls, 0)

    def test_pre_cancel_does_not_mutate_or_advance_duration_checkpoint(self):
        engine = _make_tick_engine()
        old_checkpoint = {state: 0.0 for state in AgentState}
        new_checkpoint = {
            state: (30.0 if state == AgentState.IDLE else 0.0)
            for state in AgentState
        }
        engine._state_duration_checkpoint = old_checkpoint
        engine.state_machine = SimpleNamespace(
            state=AgentState.IDLE,
            duration_totals=Mock(return_value=new_checkpoint),
        )
        cancel_event = threading.Event()
        cancel_event.set()
        before = (
            engine.ego.fatigue,
            engine.ego.stress,
            engine.ego.energy,
            engine.ego.atp_level,
            engine.ego.curiosity,
        )

        self.assertFalse(engine.cognitive_tick(30.0, cancel_event))

        self.assertEqual(engine._state_duration_checkpoint, old_checkpoint)
        self.assertEqual(
            (
                engine.ego.fatigue,
                engine.ego.stress,
                engine.ego.energy,
                engine.ego.atp_level,
                engine.ego.curiosity,
            ),
            before,
        )
        self.assertEqual(engine.ego.biological_calls, 0)
        self.assertEqual(engine.memory.gc_calls, 0)

    def test_cancel_during_biology_rolls_back_entire_phase(self):
        engine = _make_tick_engine()
        cancel_event = threading.Event()
        before = {
            name: getattr(engine.ego, name)
            for name in ("fatigue", "stress", "energy", "atp_level", "curiosity")
        }

        def cancel_from_biological_decay(_dt, _idle_seconds):
            with engine.ego.lock:
                engine.ego.biological_calls += 1
                engine.ego.stress = 0.99
                engine.ego.energy = 0.01
            cancel_event.set()

        engine.ego.apply_biological_decay = cancel_from_biological_decay
        execution_status = {}
        with patch("core.engine.cognitive_engine.os.path.exists", return_value=False):
            consumed = engine._cognitive_tick_owned(
                30.0,
                cancel_event,
                execution_status=execution_status,
            )

        self.assertFalse(consumed)
        self.assertEqual(
            {name: getattr(engine.ego, name) for name in before},
            before,
        )
        self.assertEqual(execution_status["biology_status"], "rolled_back")
        self.assertEqual(execution_status["maintenance_status"], "not_started")
        self.assertEqual(execution_status["outcome"], "cancelled")
        self.assertEqual(engine.memory.gc_calls, 0)

    def test_cancel_after_circadian_gc_candidate_runs_no_precommit_gc(self):
        engine = _make_tick_engine()
        cancel_event = threading.Event()
        initial_fatigue = engine.ego.fatigue

        def request_gc_then_cancel():
            with engine.ego.lock:
                engine.ego.circadian_calls += 1
                engine.ego.fatigue = 0.95
            cancel_event.set()
            return True

        engine.ego.apply_circadian_rhythm_deferred = request_gc_then_cancel
        execution_status = {}
        with patch("core.engine.cognitive_engine.os.path.exists", return_value=False):
            consumed = engine._cognitive_tick_owned(
                30.0,
                cancel_event,
                execution_status=execution_status,
            )

        self.assertFalse(consumed)
        self.assertEqual(engine.ego.fatigue, initial_fatigue)
        self.assertEqual(engine.memory.gc_calls, 0)
        self.assertEqual(execution_status["biology_status"], "rolled_back")
        self.assertEqual(execution_status["maintenance_status"], "not_started")
        self.assertEqual(execution_status["outcome"], "cancelled")

    def test_error_after_circadian_gc_candidate_runs_no_precommit_gc(self):
        engine = _make_tick_engine()
        initial_stress = engine.ego.stress

        class InvalidGcDecision:
            def __bool__(self):
                raise RuntimeError("circadian decision failed")

        def request_gc_then_fail_decision():
            with engine.ego.lock:
                engine.ego.stress = 0.97
            return InvalidGcDecision()

        engine.ego.apply_circadian_rhythm_deferred = (
            request_gc_then_fail_decision
        )
        execution_status = {}
        with patch("core.engine.cognitive_engine.os.path.exists", return_value=False):
            consumed = engine._cognitive_tick_owned(
                30.0,
                execution_status=execution_status,
            )

        self.assertFalse(consumed)
        self.assertEqual(engine.ego.stress, initial_stress)
        self.assertEqual(engine.memory.gc_calls, 0)
        self.assertEqual(execution_status["biology_status"], "rolled_back")
        self.assertEqual(execution_status["error_type"], "RuntimeError")
        self.assertEqual(execution_status["outcome"], "failed")

    def test_cancel_at_memory_boundary_keeps_committed_biology_observable(self):
        engine = _make_tick_engine()
        cancel_event = threading.Event()
        original_get_all = engine.memory.get_all

        def cancel_after_read():
            memories = original_get_all()
            cancel_event.set()
            return memories

        engine.memory.get_all = cancel_after_read
        execution_status = {}
        with patch("core.engine.cognitive_engine.os.path.exists", return_value=False):
            consumed = engine._cognitive_tick_owned(
                30.0,
                cancel_event,
                execution_status=execution_status,
            )

        self.assertTrue(consumed)
        self.assertEqual(execution_status["biology_status"], "committed")
        self.assertEqual(execution_status["maintenance_status"], "cancelled")
        self.assertEqual(execution_status["outcome"], "cancelled")
        self.assertEqual(engine.memory.gc_calls, 0)

    def test_state_machine_ledgers_monotonic_residency(self):
        with patch(
            "core.agent_state.time.monotonic",
            side_effect=[0.0, 10.0, 30.0, 35.0],
        ):
            machine = StateMachine()
            self.assertTrue(machine.transition(AgentState.THINKING))
            self.assertTrue(machine.transition(AgentState.IDLE))
            totals = machine.duration_totals()

        self.assertAlmostEqual(totals[AgentState.IDLE], 15.0)
        self.assertAlmostEqual(totals[AgentState.THINKING], 20.0)

    def test_tick_integrates_mixed_thinking_and_reading_residency(self):
        engine = _make_tick_engine(state=AgentState.IDLE)
        with patch("core.engine.cognitive_engine.os.path.exists", return_value=False):
            consumed = engine._cognitive_tick_owned(
                60.0,
                state_durations={
                    AgentState.THINKING: 45.0,
                    AgentState.READING: 15.0,
                },
            )

        self.assertTrue(consumed)
        # 0.2 + waking rate 0.025/h * 60 s * (1 + 0.5 * 0.2) + thinking 0.001 * 45 / 60
        self.assertAlmostEqual(
            engine.ego.fatigue, 0.2 + 0.025 / 3600 * 60 * 1.1 + 0.001 * 45 / 60
        )
        # 0.5 + 0.04 * 60 / 3600 (non-idle recovery) - 0.05 * 45 / 60 (thinking)
        self.assertAlmostEqual(engine.ego.atp_level, 0.5 + 0.04 / 60 - 0.0375)
        self.assertAlmostEqual(engine.ego.energy, 0.50875)
        self.assertAlmostEqual(engine.ego.curiosity, 0.4995)

    def test_state_mix_uses_cadence_baseline_not_startup_residency(self):
        engine = CognitiveEngine.__new__(CognitiveEngine)
        engine._state_duration_checkpoint = {
            state: (100.0 if state == AgentState.IDLE else 0.0)
            for state in AgentState
        }
        current_totals = {
            state: (
                105.0
                if state == AgentState.IDLE
                else 25.0
                if state == AgentState.THINKING
                else 0.0
            )
            for state in AgentState
        }
        engine.state_machine = SimpleNamespace(
            state=AgentState.IDLE,
            duration_totals=Mock(return_value=current_totals),
        )

        mix, snapshot = engine._state_duration_mix(30.0)

        self.assertEqual(snapshot, current_totals)
        self.assertAlmostEqual(mix[AgentState.IDLE], 5.0)
        self.assertAlmostEqual(mix[AgentState.THINKING], 25.0)

    def test_shutdown_does_not_wrap_self_locking_save_state(self):
        engine = CognitiveEngine.__new__(CognitiveEngine)
        engine.ego = _FakeEgo()
        engine.autonomous = SimpleNamespace(stop=lambda **_kwargs: None)
        engine.reader = SimpleNamespace(stop=lambda: None)

        with patch("core.engine.cognitive_engine.logger.info"):
            self._run_with_timeout(engine.shutdown)
        self.assertEqual(engine.ego.save_calls, 1)

    def test_circadian_gc_runs_after_ego_lock_is_released(self):
        ego = SelfModel.__new__(SelfModel)
        ego.lock = threading.Lock()
        ego.fatigue_critical = 1.0
        ego.fatigue = 0.0
        ego.mood = 0.0
        ego.curiosity = 0.5
        ego.atp_level = 0.1
        ego.dopamine_receptors = 1.0
        ego.last_slept_time = time.time()
        ego.days_without_sleep = 0
        ego._sleep_warning_cooldown = False

        gc_calls = []

        def collect():
            self.assertFalse(ego.lock.locked())
            gc_calls.append(True)

        ego.memory_manager = SimpleNamespace(enforce_garbage_collection=collect)

        fake_now = SimpleNamespace(hour=23, minute=0)
        fake_datetime = SimpleNamespace(now=lambda: fake_now)
        with patch("core.self_model.datetime", fake_datetime), patch("builtins.print"):
            requested = ego.apply_circadian_rhythm(defer_memory_gc=True)
            self.assertTrue(requested)
            self.assertEqual(gc_calls, [])
            ego.apply_circadian_rhythm()

        self.assertEqual(gc_calls, [True])


class RuntimeTimeTests(unittest.TestCase):
    def test_tick_decay_uses_each_memory_wall_clock_checkpoint(self):
        traces = [_RecordingTrace() for _ in range(10)]
        engine = _make_tick_engine(traces)

        with patch("core.engine.cognitive_engine.os.path.exists", return_value=False), patch(
            "core.engine.cognitive_engine.time.time", return_value=1_030.0
        ):
            engine.cognitive_tick(30.0)

        self.assertEqual(len(engine.memory.updated), 1)
        selected = engine.memory.updated[0]
        self.assertAlmostEqual(selected.elapsed_days, 30.0 / 86400.0)
        self.assertEqual(selected.last_decayed_at, 1_030.0)
        self.assertAlmostEqual(selected.stress_level, engine.ego.stress)

    def test_cancel_during_trace_decay_restores_unpersisted_trace(self):
        trace = _RecordingTrace()
        engine = _make_tick_engine([trace])
        cancel_event = threading.Event()

        def cancelling_decay(*, stress_level, elapsed_days):
            trace.stress_level = stress_level
            trace.elapsed_days = elapsed_days
            trace.last_decayed_at = -1.0
            cancel_event.set()

        trace.decay = cancelling_decay
        before = dict(trace.__dict__)
        execution_status = {}
        with patch("core.engine.cognitive_engine.os.path.exists", return_value=False), patch(
            "core.engine.cognitive_engine.time.time", return_value=1_030.0
        ):
            consumed = engine._cognitive_tick_owned(
                30.0,
                cancel_event,
                execution_status=execution_status,
            )

        self.assertTrue(consumed)
        self.assertEqual(trace.__dict__, before)
        self.assertEqual(engine.memory.updated, [])
        self.assertEqual(execution_status["biology_status"], "committed")
        self.assertEqual(execution_status["maintenance_status"], "cancelled")

    def test_memory_update_failure_restores_trace_and_reports_failed_maintenance(self):
        trace = _RecordingTrace()
        engine = _make_tick_engine([trace])

        def fail_update(memory_trace):
            engine.memory._assert_no_ego_lock()
            engine.memory.updated.append(memory_trace)
            raise RuntimeError("durable update failed")

        engine.memory.update_memory = fail_update
        before = dict(trace.__dict__)
        execution_status = {}
        with patch("core.engine.cognitive_engine.os.path.exists", return_value=False), patch(
            "core.engine.cognitive_engine.time.time", return_value=1_030.0
        ):
            consumed = engine._cognitive_tick_owned(
                30.0,
                execution_status=execution_status,
            )

        self.assertTrue(consumed)
        self.assertEqual(trace.__dict__, before)
        self.assertEqual(execution_status["biology_status"], "committed")
        self.assertEqual(execution_status["maintenance_status"], "failed")
        self.assertEqual(execution_status["error_type"], "RuntimeError")
        self.assertEqual(execution_status["outcome"], "failed")
        self.assertEqual(engine.memory.gc_calls, 0)

    def test_decay_without_elapsed_time_does_not_advance_a_day(self):
        memory = MemoryTrace(
            content="runtime regression",
            type=MemoryType.EPISODIC,
            valence=0.0,
            arousal=0.0,
            importance=0.5,
        )

        memory.decay(stress_level=0.5)
        self.assertEqual(memory.strength, 1.0)
        self.assertEqual(memory.reality_score, 1.0)

        memory.decay(stress_level=0.5, elapsed_days=-1.0)
        self.assertEqual(memory.strength, 1.0)
        self.assertTrue(math.isfinite(memory.reality_score))

    def test_sleep_resets_deprivation_clock_and_homeostasis_atomically(self):
        ego = SimpleNamespace(
            lock=threading.Lock(),
            stress=0.8,
            fatigue=0.9,
            energy=0.1,
            atp_level=0.1,
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
            save_state=Mock(),
        )

        def commit_sleep_state(completed_at):
            with ego.lock:
                ego.stress = max(0.0, ego.stress - 0.3)
                ego.fatigue = 0.0
                ego.energy = 1.0
                ego.atp_level = 1.0
                ego.last_slept_time = completed_at
                ego.days_without_sleep = 0
                ego._sleep_warning_cooldown = False
            ego.save_state()

        ego.commit_sleep_state = commit_sleep_state
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

        with patch("core.engine.memory_ops.time.time", return_value=5_000.0), patch("builtins.print"):
            controller.sleep()

        self.assertEqual(ego.last_slept_time, 5_000.0)
        self.assertEqual(ego.days_without_sleep, 0)
        self.assertFalse(ego._sleep_warning_cooldown)
        self.assertEqual(ego.fatigue, 0.0)
        self.assertEqual(ego.energy, 1.0)
        self.assertEqual(ego.atp_level, 1.0)
        self.assertFalse(ego.lock.locked())

    def test_legacy_memory_deserialization_starts_decay_at_migration_time(self):
        legacy_metadata = {
            "schema_version": "4",
            "content": "legacy memory",
            "type": "episodic",
            "valence": 0.0,
            "arousal": 0.2,
            "importance": 0.5,
            "created_at": 100.0,
            "last_recalled": 100.0,
            "strength": 0.8,
        }

        store = object.__new__(VectorStore)
        with patch("components.vector_store.time.time", return_value=5_000.0):
            memory = store._dict_to_obj(legacy_metadata)

        self.assertIsNotNone(memory)
        self.assertEqual(memory.created_at, 100.0)
        self.assertEqual(memory.last_decayed_at, 5_000.0)
        self.assertEqual(memory.strength, 0.8)

    def test_monotonic_tick_gate_uses_configured_interval(self):
        with patch.object(Config, "COGNITIVE_TICK_INTERVAL_SECONDS", 30.0, create=True):
            controller = AutonomousController(SimpleNamespace())

        self.assertIsNone(controller._tick_delta_if_due(100.0, 129.999))
        self.assertEqual(controller._tick_delta_if_due(100.0, 130.0), 30.0)
        self.assertEqual(controller._tick_delta_if_due(100.0, 145.5), 45.5)
        self.assertIsNone(controller._tick_delta_if_due(100.0, 99.0))

    def test_tick_guard_rejects_overlap_after_timeout(self):
        started = threading.Event()
        release = threading.Event()
        calls = []

        def blocking_tick(dt, cancel_event):
            calls.append(dt)
            started.set()
            release.wait(1.0)

        controller = AutonomousController(SimpleNamespace(cognitive_tick=blocking_tick))
        first = threading.Thread(
            target=controller._run_cognitive_tick_guarded,
            args=(30.0, threading.Event()),
            daemon=True,
        )
        first.start()
        self.assertTrue(started.wait(1.0))
        self.assertFalse(controller._run_cognitive_tick_guarded(30.0, threading.Event()))
        release.set()
        first.join(1.0)

        self.assertFalse(first.is_alive())
        self.assertEqual(calls, [30.0])

    def test_tick_guard_marks_only_an_acquired_worker_as_started(self):
        release = threading.Event()
        first_started = threading.Event()

        def blocking_tick(dt, cancel_event):
            release.wait(1.0)

        controller = AutonomousController(SimpleNamespace(cognitive_tick=blocking_tick))
        first = threading.Thread(
            target=controller._run_cognitive_tick_guarded,
            args=(30.0, threading.Event(), first_started),
            daemon=True,
        )
        first.start()
        self.assertTrue(first_started.wait(1.0))

        skipped_started = threading.Event()
        self.assertFalse(
            controller._run_cognitive_tick_guarded(
                60.0, threading.Event(), skipped_started
            )
        )
        self.assertFalse(skipped_started.is_set())
        release.set()
        first.join(1.0)

    def test_identity_reflection_persists_the_new_insight(self):
        ego = SimpleNamespace(
            lock=threading.Lock(),
            # A revision of the current self, not a wholesale rewrite.
            evolved_insight="I verify changes.",
            actionable_lessons=[],
        )
        result = {
            "insight": "I verify changes before trusting them.",
            "actionable_lessons": ["Verify evidence"],
            "value_updates": [],
        }
        engine = SimpleNamespace(
            ego=ego,
            stm_lock=threading.Lock(),
            short_term_buffer=["one", "two", "three", "four"],
            value_system=SimpleNamespace(get_moral_context=Mock(return_value="values")),
            llm=SimpleNamespace(generate_text=Mock(return_value=(json.dumps(result), 0.0))),
            memory=SimpleNamespace(add_memory=Mock()),
        )
        controller = object.__new__(MemoryOperationsController)
        controller.engine = engine

        with patch("core.utils.atomic_write_json") as write_json, patch("builtins.print"):
            controller._identity_evolution_phase()

        self.assertEqual(ego.evolved_insight, result["insight"])
        self.assertEqual(ego.actionable_lessons, ["Verify evidence"])
        persisted = write_json.call_args.args[1]
        self.assertEqual(persisted["evolved_insight"], result["insight"])


if __name__ == "__main__":
    unittest.main()
