import threading
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch

from config import Config
from core.agent_state import StateMachine
from core.engine.cognitive_engine import CognitiveEngine


class _Stopper:
    def __init__(self, events, name, result=True):
        self._events = events
        self._name = name
        self._result = result

    def shutdown(self, **_kwargs):
        self._events.append(self._name)
        return self._result

    def stop(self, **_kwargs):
        self._events.append(self._name)
        return self._result


class _Ledger:
    def __init__(self, events, gate=None, *, fail=False):
        self._events = events
        self._gate = gate
        self._fail = fail
        self.close_calls = 0

    def close(self):
        self.close_calls += 1
        if self._gate is not None:
            if not self._gate.locked():
                raise AssertionError("ledger closed without owning mutation gate")
        self._events.append("ledger")
        if self._fail:
            raise RuntimeError("ledger close failed")


def _shutdown_engine(*, actor_result=True, owns_ledger=True, ledger_fail=False):
    events = []
    engine = CognitiveEngine.__new__(CognitiveEngine)
    engine._owns_memory = True
    engine._owns_operation_ledger = owns_ledger
    engine._operation_ledger_close_attempted = False
    engine.state_machine = StateMachine()
    engine._runtime_mutation_gate = threading.Lock()
    engine._shutdown_lock = threading.Lock()
    engine._shutdown_complete = False
    engine._shutdown_result = None
    engine.interaction_actor = _Stopper(events, "actor", actor_result)
    engine.autonomous = _Stopper(events, "autonomous")
    engine.reader = Mock()
    engine.reader.stop.side_effect = lambda: events.append("reader")
    engine.ego = Mock()
    engine.ego.save_state.side_effect = lambda: events.append("save")
    engine.memory = Mock()
    engine.memory.close.side_effect = lambda: events.append("memory")
    engine.operation_ledger = _Ledger(
        events,
        engine._runtime_mutation_gate,
        fail=ledger_fail,
    )
    return engine, events


class OperationLedgerInitializationTests(unittest.TestCase):
    @staticmethod
    def _patch_non_ledger_dependencies(stack):
        registry = SimpleNamespace(engine=None, load=Mock())
        reader = Mock()
        stack.enter_context(patch.object(Config, "EVENT_JOURNAL_ENABLED", False))
        stack.enter_context(
            patch("core.tools.get_skill_registry", return_value=registry)
        )
        stack.enter_context(
            patch("core.engine.cognitive_engine.BackgroundReader", return_value=reader)
        )
        stack.enter_context(patch("core.world_graph.WorldGraph", return_value=Mock()))
        stack.enter_context(patch("core.value_system.ValueSystem", return_value=Mock()))
        stack.enter_context(
            patch("core.local_perception.LocalPerception", return_value=Mock())
        )
        stack.enter_context(
            patch("core.engine.cognitive_engine.PerceptionController", return_value=Mock())
        )
        stack.enter_context(
            patch("core.engine.cognitive_engine.InteractionController", return_value=Mock())
        )
        stack.enter_context(
            patch("core.engine.cognitive_engine.InteractionActor", return_value=Mock())
        )
        stack.enter_context(
            patch("core.engine.cognitive_engine.AutonomousController", return_value=Mock())
        )
        stack.enter_context(
            patch("core.engine.cognitive_engine.SLMCore", return_value=Mock())
        )
        stack.enter_context(
            patch("core.engine.cognitive_engine.os.path.exists", return_value=True)
        )
        return reader

    def test_production_ledger_exists_before_memory_controller_construction(self):
        events = []
        ledger = _Ledger(events)
        memory_ops = Mock()
        engine = CognitiveEngine.__new__(CognitiveEngine)
        ego = Mock()

        def make_ledger():
            events.append("ledger_created")
            return ledger

        def make_memory_ops(observed_engine):
            self.assertIs(observed_engine.operation_ledger, ledger)
            events.append("memory_ops_created")
            return memory_ops

        with ExitStack() as stack:
            self._patch_non_ledger_dependencies(stack)
            stack.enter_context(
                patch(
                    "core.engine.cognitive_engine.OperationLedger",
                    side_effect=make_ledger,
                )
            )
            stack.enter_context(
                patch(
                    "core.engine.cognitive_engine.MemoryOperationsController",
                    side_effect=make_memory_ops,
                )
            )
            engine._initialize(
                llm=Mock(),
                embedder=Mock(),
                memory=Mock(),
                ego=ego,
                operation_ledger=None,
            )

        self.assertEqual(events[:2], ["ledger_created", "memory_ops_created"])
        memory_ops.load_short_term_memory.assert_called_once_with()

    def test_ledger_initialization_failure_is_not_downgraded(self):
        memory_ops_type = Mock()
        with ExitStack() as stack:
            reader = self._patch_non_ledger_dependencies(stack)
            stack.enter_context(
                patch(
                    "core.engine.cognitive_engine.OperationLedger",
                    side_effect=RuntimeError("ledger unavailable"),
                )
            )
            stack.enter_context(
                patch(
                    "core.engine.cognitive_engine.MemoryOperationsController",
                    memory_ops_type,
                )
            )
            with self.assertRaisesRegex(RuntimeError, "ledger unavailable"):
                CognitiveEngine(
                    llm=Mock(),
                    embedder=Mock(),
                    memory=Mock(),
                    ego=Mock(),
                )

        memory_ops_type.assert_not_called()
        reader.stop.assert_called_once_with()

    def test_safe_partial_initialization_closes_owned_ledger_after_workers(self):
        events = []
        ledger = _Ledger(events)
        memory = Mock()
        memory.close.side_effect = lambda: events.append("memory")

        def fail_initialize(engine, **_kwargs):
            engine.memory = memory
            engine.operation_ledger = ledger
            engine.interaction_actor = _Stopper(events, "actor")
            engine.autonomous = _Stopper(events, "autonomous")
            engine.reader = _Stopper(events, "reader")
            raise RuntimeError("late init failure")

        with patch.object(CognitiveEngine, "_initialize", new=fail_initialize):
            with self.assertRaisesRegex(RuntimeError, "late init failure"):
                CognitiveEngine()

        self.assertEqual(
            events,
            ["actor", "autonomous", "reader", "ledger", "memory"],
        )
        self.assertEqual(ledger.close_calls, 1)

    def test_partial_worker_survival_retains_owned_ledger(self):
        events = []
        ledger = _Ledger(events)
        memory = Mock()

        def fail_initialize(engine, **_kwargs):
            engine.memory = memory
            engine.operation_ledger = ledger
            engine.interaction_actor = _Stopper(events, "actor", False)
            raise RuntimeError("late init failure")

        with patch.object(CognitiveEngine, "_initialize", new=fail_initialize):
            with self.assertRaisesRegex(RuntimeError, "late init failure"):
                CognitiveEngine()

        self.assertEqual(events, ["actor"])
        self.assertEqual(ledger.close_calls, 0)
        memory.close.assert_not_called()

    def test_partial_tick_survival_retains_owned_ledger(self):
        events = []
        ledger = _Ledger(events)
        memory = Mock()
        gate = threading.Lock()
        gate.acquire()

        def fail_initialize(engine, **_kwargs):
            engine.memory = memory
            engine.operation_ledger = ledger
            engine.state_machine = StateMachine()
            engine._runtime_mutation_gate = gate
            raise RuntimeError("late init failure")

        try:
            with patch.object(
                Config,
                "INTERACTION_SHUTDOWN_TIMEOUT_SECONDS",
                0.01,
            ), patch.object(
                CognitiveEngine,
                "_initialize",
                new=fail_initialize,
            ):
                with self.assertRaisesRegex(RuntimeError, "late init failure"):
                    CognitiveEngine()
        finally:
            gate.release()

        self.assertEqual(ledger.close_calls, 0)
        memory.close.assert_not_called()


class OperationLedgerShutdownTests(unittest.TestCase):
    def test_owned_ledger_closes_once_after_quiescence(self):
        engine, events = _shutdown_engine()

        self.assertTrue(engine.shutdown())
        self.assertTrue(engine.shutdown())

        self.assertEqual(
            events,
            ["actor", "autonomous", "reader", "save", "memory", "ledger"],
        )
        self.assertEqual(engine.operation_ledger.close_calls, 1)

    def test_worker_degraded_shutdown_does_not_close_ledger(self):
        engine, events = _shutdown_engine(actor_result=False)

        self.assertFalse(engine.shutdown())

        self.assertEqual(events, ["actor", "autonomous"])
        self.assertEqual(engine.operation_ledger.close_calls, 0)

    def test_caller_owned_injected_ledger_is_not_closed(self):
        engine, events = _shutdown_engine(owns_ledger=False)

        self.assertTrue(engine.shutdown())

        self.assertEqual(
            events,
            ["actor", "autonomous", "reader", "save", "memory"],
        )
        self.assertEqual(engine.operation_ledger.close_calls, 0)

    def test_close_failure_is_terminal_and_not_retried(self):
        engine, events = _shutdown_engine(ledger_fail=True)

        self.assertFalse(engine.shutdown())
        self.assertFalse(engine.shutdown())

        self.assertEqual(engine.operation_ledger.close_calls, 1)
        self.assertEqual(events.count("ledger"), 1)
        self.assertTrue(engine._shutdown_complete)

    def test_close_failure_remains_failed_across_persistence_retry(self):
        engine, events = _shutdown_engine(ledger_fail=True)
        save_calls = 0

        def save_state():
            nonlocal save_calls
            save_calls += 1
            events.append("save")
            if save_calls == 1:
                raise RuntimeError("state save failed")

        engine.ego.save_state.side_effect = save_state

        self.assertFalse(engine.shutdown())
        self.assertFalse(engine.shutdown())

        self.assertEqual(engine.operation_ledger.close_calls, 1)
        self.assertEqual(events.count("ledger"), 1)
        self.assertTrue(engine._shutdown_complete)


if __name__ == "__main__":
    unittest.main()
