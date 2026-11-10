import asyncio
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.agent_state import AgentState
from core.engine.autonomous import AutonomousController
from core.engine.bio_controller import BioController
from core.engine.reflex_gate import ReflexGate
from core.memory import MemoryTrace, MemoryType
from core.self_model import SelfModel, _validated_persisted_state


def _trace(**overrides):
    values = dict(content="ký ức", type=MemoryType.EMOTIONAL, valence=-0.8,
                  arousal=0.9, importance=0.9)
    values.update(overrides)
    return MemoryTrace(**values)


class RuminationDoesNotImmortalizeTests(unittest.TestCase):
    def test_passive_rumination_never_deep_freezes_a_memory(self):
        mem = _trace()
        with patch("builtins.print"):
            for _ in range(100):
                mem.reconsolidate(-0.8, is_associative=True, count_recall=False)
                mem.decay(stress_level=0.5, elapsed_days=0.01)
        self.assertEqual(mem.recall_count, 0)
        self.assertFalse(mem.is_flashbulb)

    def test_active_recall_still_counts(self):
        mem = _trace()
        mem.reconsolidate(0.0)
        self.assertEqual(mem.recall_count, 1)

    def test_mind_stream_skips_just_recalled_memories(self):
        now = time.time()
        fresh = _trace(content="vừa nghĩ", last_recalled=now - 60)
        older = _trace(content="lâu rồi", last_recalled=now - 3 * 3600)
        engine = SimpleNamespace(
            memory=SimpleNamespace(get_all=lambda: [fresh, older]),
            ego=SimpleNamespace(mood=-0.5),
        )
        controller = AutonomousController(engine)
        picked = controller._weighted_sample_memories(
            1, mood_congruent=True, exclude_recent_seconds=30 * 60
        )
        self.assertEqual(picked, [older])


class SeparationMemoryTests(unittest.TestCase):
    def _controller(self, existing):
        memory = SimpleNamespace(
            get_all=Mock(return_value=existing),
            update_memory=Mock(),
            add_memory=Mock(),
        )
        engine = SimpleNamespace(memory=memory)
        return AutonomousController(engine), memory

    def test_existing_separation_memory_is_deepened_not_duplicated(self):
        mem = _trace(origin_kind="separation_anxiety", valence=-0.5, importance=0.6, scope="agent")
        controller, memory = self._controller([mem])
        self.assertTrue(controller._deepen_separation_memory(2, 26.0))
        memory.update_memory.assert_called_once_with(mem)
        memory.add_memory.assert_not_called()
        self.assertEqual(mem.emotional_layers, 2)
        self.assertEqual(mem.valence, -0.7)
        self.assertLessEqual(mem.importance, 0.8)
        self.assertIn("nhớ 26 giờ", mem.overlays[-1])

    def test_without_existing_memory_a_new_one_is_needed(self):
        controller, memory = self._controller([_trace(origin_kind="reading")])
        self.assertFalse(controller._deepen_separation_memory(1, 6.0))
        memory.update_memory.assert_not_called()


def _ego(**overrides):
    ego = SelfModel.__new__(SelfModel)
    ego.lock = threading.Lock()
    ego.mood = 0.0
    ego.stress = 0.1
    ego.fatigue = 0.0
    ego.integrity = 1.0
    ego.resilience = 0.0
    ego.dopamine_receptors = 1.0
    ego.is_stranger = False
    ego.current_intimacy = 0.5
    ego.mood_anchor = None
    ego.mood_anchor_duration = 0.0
    ego.bio_controller = BioController()
    for name, value in overrides.items():
        setattr(ego, name, value)
    return ego


class IntimacyTests(unittest.TestCase):
    def test_owner_intimacy_grows_with_warm_conversations(self):
        ego = _ego()
        with patch("builtins.print"):
            for _ in range(15):
                ego.update_state({"valence": 0.6, "arousal": 0.3})
        self.assertGreater(ego.current_intimacy, 0.6)

    def test_hurtful_exchanges_reduce_intimacy(self):
        ego = _ego(current_intimacy=0.7)
        with patch("builtins.print"):
            ego.update_state({"valence": -0.8, "arousal": 0.5})
        self.assertAlmostEqual(ego.current_intimacy, 0.7 - 0.03 * 0.8)

    def test_stranger_warms_up_faster_from_zero(self):
        ego = _ego(is_stranger=True, current_intimacy=0.0)
        with patch("builtins.print"):
            ego.update_state({"valence": 0.5, "arousal": 0.0})
        self.assertAlmostEqual(ego.current_intimacy, 0.05)

    def test_intimacy_is_persisted_and_bounded(self):
        self.assertEqual(
            _validated_persisted_state({"current_intimacy": 0.8})["current_intimacy"], 0.8
        )
        with self.assertRaises(ValueError):
            _validated_persisted_state({"current_intimacy": 1.5})


class SpiralRecoveryScenarioTests(unittest.TestCase):
    def test_warm_days_let_trauma_heal(self):
        """Without intimacy > 0.6 healing never ran for the owner; now it can."""
        ego = _ego()
        trauma = _trace(is_flashbulb=True, valence=-0.8)
        with patch("builtins.print"):
            ego.process_trauma_healing(trauma)
            self.assertEqual(trauma.valence, -0.8)  # baseline intimacy: no healing
            for _day in range(3):
                for _ in range(10):  # an evening of warm conversation
                    ego.update_state({"valence": 0.7, "arousal": 0.3})
                ego.process_trauma_healing(trauma)  # nightly reconsolidation
        self.assertGreater(ego.current_intimacy, 0.6)
        self.assertGreater(trauma.valence, -0.8)
        self.assertGreater(ego.resilience, 0.0)


class SleepReflexTests(unittest.TestCase):
    def _gate(self, fatigue):
        return ReflexGate(SimpleNamespace(ego=SimpleNamespace(fatigue=fatigue, curiosity=1.0)))

    def test_moderately_tired_aura_does_not_doze_off_mid_chat(self):
        gate = self._gate(0.7)
        self.assertFalse(any(gate.evaluate_reflexes()["triggered"] for _ in range(1000)))

    def test_exhausted_aura_usually_needs_sleep(self):
        gate = self._gate(0.98)
        hits = sum(gate.evaluate_reflexes()["triggered"] for _ in range(1000))
        self.assertGreater(hits, 700)

    def test_no_unhandled_search_reflex(self):
        gate = self._gate(0.0)
        self.assertFalse(any(gate.evaluate_reflexes()["triggered"] for _ in range(2000)))

    def test_requested_sleep_runs_at_next_idle_decision(self):
        machine = SimpleNamespace(state=AgentState.IDLE)
        machine.transition = lambda state: setattr(machine, "state", state) or True
        engine = SimpleNamespace(
            ego=SimpleNamespace(
                get_drive_status=lambda: {"dominant": "curiosity", "dominant_value": 0.3},
            ),
            state_machine=machine,
            last_interaction_time=time.time(),
            memory_ops=SimpleNamespace(sleep=Mock()),
        )
        controller = AutonomousController(engine)
        controller.request_sleep()
        with patch("builtins.print"):
            asyncio.run(controller._run_autonomous_decisions(10.0, 1.0))
        engine.memory_ops.sleep.assert_called_once()
        self.assertFalse(controller._sleep_requested)
        self.assertEqual(machine.state, AgentState.IDLE)


if __name__ == "__main__":
    unittest.main()
