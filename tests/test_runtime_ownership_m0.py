import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from core.agent_state import AgentState, StateMachine
from core.engine.autonomous import AutonomousController
from core.engine.cognitive_engine import CognitiveEngine
from core.skills import Skill, SkillRegistry


class CognitiveTickOwnershipTests(unittest.TestCase):
    def test_tick_refuses_held_runtime_gate_without_mutating(self):
        engine = CognitiveEngine.__new__(CognitiveEngine)
        engine._runtime_mutation_gate = threading.Lock()
        engine._cognitive_tick_owned = Mock(return_value=True)

        self.assertTrue(engine._runtime_mutation_gate.acquire(blocking=False))
        try:
            self.assertFalse(engine.cognitive_tick(dt=17.5))
            engine._cognitive_tick_owned.assert_not_called()
            self.assertTrue(engine._runtime_mutation_gate.locked())
        finally:
            engine._runtime_mutation_gate.release()


class AutonomousRuntimeOwnershipTests(unittest.TestCase):
    @staticmethod
    def _controller(initial=AgentState.IDLE):
        state_machine = StateMachine(initial)
        engine = SimpleNamespace(
            state_machine=state_machine,
            _runtime_mutation_gate=threading.Lock(),
        )
        return AutonomousController(engine), engine

    def test_successful_claim_holds_gate_until_exact_state_release(self):
        controller, engine = self._controller()
        original_transition = engine.state_machine.transition
        engine.state_machine.transition = Mock(wraps=original_transition)

        self.assertTrue(controller._try_claim_runtime_state(AgentState.THINKING))
        self.assertEqual(engine.state_machine.state, AgentState.THINKING)
        self.assertTrue(engine._runtime_mutation_gate.locked())
        self.assertFalse(engine._runtime_mutation_gate.acquire(blocking=False))

        controller._release_runtime_state(AgentState.THINKING)

        self.assertEqual(engine.state_machine.state, AgentState.IDLE)
        self.assertEqual(
            engine.state_machine.transition.call_args_list,
            [call(AgentState.THINKING), call(AgentState.IDLE)],
        )
        self.assertTrue(engine._runtime_mutation_gate.acquire(blocking=False))
        engine._runtime_mutation_gate.release()

    def test_failed_transition_returns_gate_to_next_owner(self):
        controller, engine = self._controller(initial=AgentState.THINKING)
        original_transition = engine.state_machine.transition
        engine.state_machine.transition = Mock(wraps=original_transition)

        self.assertFalse(controller._try_claim_runtime_state(AgentState.READING))
        self.assertEqual(engine.state_machine.state, AgentState.THINKING)
        engine.state_machine.transition.assert_called_once_with(AgentState.READING)
        self.assertTrue(engine._runtime_mutation_gate.acquire(blocking=False))
        engine._runtime_mutation_gate.release()

    def test_busy_gate_rejects_claim_without_touching_state(self):
        controller, engine = self._controller()
        original_transition = engine.state_machine.transition
        engine.state_machine.transition = Mock(wraps=original_transition)

        self.assertTrue(engine._runtime_mutation_gate.acquire(blocking=False))
        try:
            self.assertFalse(controller._try_claim_runtime_state(AgentState.READING))
            self.assertEqual(engine.state_machine.state, AgentState.IDLE)
            engine.state_machine.transition.assert_not_called()
            self.assertTrue(engine._runtime_mutation_gate.locked())
        finally:
            engine._runtime_mutation_gate.release()


class SkillRegistrySynchronousMutationTests(unittest.TestCase):
    @staticmethod
    def _registry():
        registry = SkillRegistry()
        registry._save_unsafe = Mock()
        registry.register(
            Skill(
                "search_novel",
                "test search",
                "ACTION: search_novel | <query>",
                lambda arg: registry._reader_action(arg, "search_novel"),
            )
        )
        registry.register(
            Skill(
                "start_reading",
                "test read",
                "ACTION: start_reading | now",
                lambda arg: registry._autonomous_action(arg, "start_reading"),
            )
        )
        return registry

    def test_search_returns_real_reader_result_on_calling_thread(self):
        registry = self._registry()
        caller_thread = threading.get_ident()
        observed_threads = []

        def search_and_set_novel(query):
            observed_threads.append(threading.get_ident())
            return f"loaded:{query}"

        registry.engine = SimpleNamespace(
            reader=SimpleNamespace(search_and_set_novel=search_and_set_novel)
        )

        with patch(
            "threading.Thread",
            side_effect=AssertionError("skill must not spawn a detached thread"),
        ):
            result = registry.execute("search_novel", "Dune")

        self.assertEqual(result, "loaded:Dune")
        self.assertEqual(observed_threads, [caller_thread])

    def test_actor_owned_reading_completes_inline_without_daemon_mutation(self):
        registry = self._registry()
        caller_thread = threading.get_ident()
        observed_threads = []

        def do_reading_session():
            observed_threads.append(threading.get_ident())

        autonomous = SimpleNamespace(
            _do_reading_session=Mock(side_effect=do_reading_session),
            start_reading_task=Mock(return_value=True),
        )
        registry.engine = SimpleNamespace(
            interaction_actor=SimpleNamespace(is_owner_thread=True),
            autonomous=autonomous,
        )

        with patch(
            "threading.Thread",
            side_effect=AssertionError("skill must not spawn a detached thread"),
        ):
            result = registry.execute("start_reading", "now")

        self.assertIsInstance(result, str)
        self.assertTrue(result)
        self.assertEqual(observed_threads, [caller_thread])
        autonomous._do_reading_session.assert_called_once_with()
        autonomous.start_reading_task.assert_not_called()


class AutonomousShutdownContractTests(unittest.TestCase):
    def test_stop_reports_false_when_worker_survives_timeout(self):
        controller = AutonomousController(SimpleNamespace())
        stubborn_thread = Mock()
        stubborn_thread.is_alive.return_value = True
        controller._loop_thread = stubborn_thread

        self.assertFalse(controller.stop(timeout=0.025))
        stubborn_thread.join.assert_called_once_with(timeout=0.025)
        self.assertTrue(controller._stop_event.is_set())


if __name__ == "__main__":
    unittest.main()
