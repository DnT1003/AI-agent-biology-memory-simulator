import threading
import unittest
from unittest.mock import Mock, patch

from config import Config
from core.agent_state import AgentState, StateMachine
from core.engine.autonomous import AutonomousController
from core.engine.cognitive_engine import CognitiveEngine


class _Stopper:
    def __init__(self, events, name, result=True):
        self.events = events
        self.name = name
        self.result = result
        self.calls = 0

    def shutdown(self, **kwargs):
        self.calls += 1
        self.events.append(self.name)
        return self.result

    def stop(self, **kwargs):
        self.calls += 1
        self.events.append(self.name)
        return self.result


def _engine_for_shutdown(*, actor_result=True, autonomous_result=True):
    events = []
    engine = CognitiveEngine.__new__(CognitiveEngine)
    engine.state_machine = StateMachine()
    engine._runtime_mutation_gate = threading.Lock()
    engine._shutdown_lock = threading.Lock()
    engine._shutdown_complete = False
    engine.interaction_actor = _Stopper(events, "actor", actor_result)
    engine.autonomous = _Stopper(events, "autonomous", autonomous_result)
    engine.reader = Mock()
    engine.reader.stop.side_effect = lambda: events.append("reader")
    engine.memory_ops = Mock()
    engine.memory_ops.sleep.side_effect = lambda: events.append("consolidate")
    engine.ego = Mock()
    engine.ego.save_state.side_effect = lambda: events.append("save")
    return engine, events


class CognitiveEngineShutdownTests(unittest.TestCase):
    def test_shutdown_quiesces_then_saves_without_simulating_sleep(self):
        engine, events = _engine_for_shutdown()

        self.assertTrue(engine.shutdown(consolidate=True))
        self.assertEqual(engine.state_machine.state, AgentState.SHUTDOWN)
        self.assertEqual(
            events, ["actor", "autonomous", "reader", "save"]
        )
        engine.memory_ops.sleep.assert_not_called()
        self.assertTrue(engine.shutdown(consolidate=True))
        self.assertEqual(
            events, ["actor", "autonomous", "reader", "save"]
        )

    def test_unstopped_worker_skips_reader_consolidation_and_save(self):
        engine, events = _engine_for_shutdown(actor_result=False)

        self.assertFalse(engine.shutdown(consolidate=True))
        self.assertEqual(engine.state_machine.state, AgentState.SHUTDOWN)
        self.assertEqual(events, ["actor", "autonomous"])
        engine.reader.stop.assert_not_called()
        engine.memory_ops.sleep.assert_not_called()
        engine.ego.save_state.assert_not_called()

    def test_optional_cleanup_failure_still_saves_base_state(self):
        engine, events = _engine_for_shutdown()
        engine.reader.stop.side_effect = RuntimeError("browser close failed")

        self.assertFalse(engine.shutdown())
        engine.ego.save_state.assert_called_once()
        self.assertTrue(engine._shutdown_complete)
        self.assertFalse(engine.shutdown())
        engine.ego.save_state.assert_called_once()

    def test_discord_transport_is_stopped_before_state_save(self):
        engine, events = _engine_for_shutdown()
        engine.discord_bridge = _Stopper(events, "discord")

        self.assertTrue(engine.shutdown())
        self.assertEqual(
            events, ["actor", "autonomous", "discord", "reader", "save"]
        )

    def test_owned_mutation_gate_prevents_torn_save(self):
        engine, events = _engine_for_shutdown()
        self.assertTrue(engine._runtime_mutation_gate.acquire(blocking=False))
        try:
            with patch.object(
                Config, "INTERACTION_SHUTDOWN_TIMEOUT_SECONDS", 0.01
            ):
                self.assertFalse(engine.shutdown(consolidate=True))
        finally:
            engine._runtime_mutation_gate.release()

        self.assertEqual(events, ["actor", "autonomous"])
        engine.ego.save_state.assert_not_called()


class AutonomousStopTests(unittest.TestCase):
    def test_start_refuses_terminal_engine(self):
        engine = Mock()
        engine.state_machine = StateMachine(AgentState.SHUTDOWN)
        controller = AutonomousController(engine)

        self.assertFalse(controller.start())
        self.assertIsNone(controller._loop_thread)

    def test_stop_is_idempotent_without_touching_closed_loop(self):
        controller = AutonomousController(Mock())
        dead_thread = Mock()
        dead_thread.is_alive.return_value = False
        closed_loop = Mock()
        closed_loop.is_closed.return_value = True
        controller._loop_thread = dead_thread
        controller._loop = closed_loop

        self.assertTrue(controller.stop(timeout=0.0))
        self.assertTrue(controller.stop(timeout=0.0))
        closed_loop.call_soon_threadsafe.assert_not_called()

    def test_stop_reports_thread_that_misses_deadline(self):
        controller = AutonomousController(Mock())
        live_thread = Mock()
        live_thread.is_alive.return_value = True
        controller._loop_thread = live_thread
        controller._loop = None

        self.assertFalse(controller.stop(timeout=0.0))
        live_thread.join.assert_called_once_with(timeout=0.0)


if __name__ == "__main__":
    unittest.main()
