import copy
import unittest
from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.engine.memory_ops import MemoryOperationsController
from core.memory import MemoryTrace, MemoryType


def _trace(record_id: str, *, strength: float = 1.0) -> MemoryTrace:
    return MemoryTrace(
        id=record_id,
        content=f"content-{record_id}",
        type=MemoryType.EPISODIC,
        valence=0.0,
        arousal=0.0,
        importance=0.5,
        strength=strength,
        created_at=1_000.0,
        last_recalled=1_000.0,
        last_decayed_at=1_000.0,
    )


def _controller(search):
    memory = SimpleNamespace(
        search_memories=Mock(side_effect=search),
        chronological_recall=Mock(return_value=[]),
        update_memory=Mock(),
        upsert_memory=Mock(),
    )
    llm = SimpleNamespace(generate_text=Mock(return_value=("unchanged", {})))
    controller = object.__new__(MemoryOperationsController)
    controller.engine = SimpleNamespace(
        memory=memory,
        llm=llm,
        ego=SimpleNamespace(mood=0.0, stress=0.0, fatigue=0.0),
    )
    return controller, memory, llm


class PureRecallPlanningTests(unittest.TestCase):
    def test_plan_is_immutable_and_has_no_llm_write_or_memory_mutation(self):
        anchor = _trace("anchor")
        associated = _trace("associated", strength=0.8)

        def search(query, *, top_k):
            if query == "query":
                return [(0.9, anchor)]
            if query == anchor.content:
                return [(0.7, associated)]
            return []

        controller, memory, llm = _controller(search)
        before = {
            trace.id: copy.deepcopy(trace.__dict__)
            for trace in (anchor, associated)
        }

        with patch.object(anchor, "reconsolidate") as anchor_effect, patch.object(
            associated, "reconsolidate"
        ) as associated_effect, patch(
            "core.engine.memory_ops.random.random",
            side_effect=AssertionError("planner used randomness"),
        ):
            plan = controller.build_recall_plan("query", now=5_000.0)

        self.assertEqual(
            [hit.memory.id for hit in plan.hits],
            ["anchor", "associated"],
        )
        self.assertFalse(plan.hits[0].is_associative)
        self.assertTrue(plan.hits[1].is_associative)
        anchor_effect.assert_not_called()
        associated_effect.assert_not_called()
        llm.generate_text.assert_not_called()
        memory.update_memory.assert_not_called()
        memory.upsert_memory.assert_not_called()
        self.assertEqual(anchor.__dict__, before[anchor.id])
        self.assertEqual(associated.__dict__, before[associated.id])
        with self.assertRaises(FrozenInstanceError):
            plan.mood = 0.5

    def test_repeated_plan_has_stable_score_then_id_order(self):
        first = _trace("a")
        second = _trace("b")
        assoc_first = _trace("c", strength=0.8)
        assoc_second = _trace("d", strength=0.8)
        primary_calls = 0
        associative_calls = 0

        def search(query, *, top_k):
            nonlocal primary_calls, associative_calls
            if query == "query":
                primary_calls += 1
                ordered = [(0.9, second), (0.9, first)]
                return ordered if primary_calls == 1 else list(reversed(ordered))
            if query == first.content:
                associative_calls += 1
                ordered = [(0.7, assoc_second), (0.7, assoc_first)]
                return ordered if associative_calls == 1 else list(reversed(ordered))
            return []

        controller, _memory, _llm = _controller(search)

        first_plan = controller.build_recall_plan("query", now=5_000.0)
        second_plan = controller.build_recall_plan("query", now=5_000.0)

        first_ids = [hit.memory.id for hit in first_plan.hits]
        second_ids = [hit.memory.id for hit in second_plan.hits]
        self.assertEqual(first_ids, ["a", "b", "c"])
        self.assertEqual(second_ids, first_ids)

    def test_fixed_now_makes_temporal_plan_repeatable(self):
        first = _trace("a")
        second = _trace("b")

        def search(_query, *, top_k):
            return []

        controller, memory, _llm = _controller(search)
        memory.chronological_recall.return_value = [second, first]

        plan_one = controller.build_recall_plan("hôm nay", now=400_000.0)
        plan_two = controller.build_recall_plan("hôm nay", now=400_000.0)

        self.assertEqual(
            [hit.memory.id for hit in plan_one.hits],
            ["a", "b"],
        )
        self.assertEqual(
            [hit.memory.id for hit in plan_two.hits],
            ["a", "b"],
        )
        for call in memory.chronological_recall.call_args_list:
            self.assertEqual(
                call.args,
                (400_000.0 - 86400 * 3, 400_000.0),
            )

    def test_plan_works_with_read_only_memory_capability(self):
        anchor = _trace("read-only")

        class ReadOnlyMemory:
            def search_memories(self, query, *, top_k):
                if query == "query":
                    return [(0.9, anchor)]
                return []

            def chronological_recall(self, start, end, *, limit):
                return []

        controller = object.__new__(MemoryOperationsController)
        controller.engine = SimpleNamespace(
            memory=ReadOnlyMemory(),
            llm=SimpleNamespace(generate_text=Mock()),
            ego=SimpleNamespace(mood=0.0, stress=0.0, fatigue=0.0),
        )

        plan = controller.build_recall_plan("query", now=5_000.0)

        self.assertEqual([hit.memory.id for hit in plan.hits], ["read-only"])


class RecallEffectsTests(unittest.TestCase):
    def test_wrapper_applies_primary_and_associative_effects(self):
        anchor = _trace("anchor")
        associated = _trace("associated", strength=0.8)
        anchor.reconsolidate = Mock(return_value=False)
        associated.reconsolidate = Mock(return_value=False)

        def search(query, *, top_k):
            if query == "query":
                return [(0.9, anchor)]
            if query == anchor.content:
                return [(0.7, associated)]
            return []

        controller, memory, llm = _controller(search)

        recalled = controller.recall("query")

        self.assertEqual([trace.id for trace in recalled], ["anchor", "associated"])
        anchor.reconsolidate.assert_called_once_with(
            0.0,
            is_associative=False,
        )
        associated.reconsolidate.assert_called_once_with(
            0.0,
            is_associative=True,
        )
        self.assertEqual(
            [call.args[0].id for call in memory.update_memory.call_args_list],
            ["anchor", "associated"],
        )
        memory.upsert_memory.assert_not_called()
        llm.generate_text.assert_not_called()

    def test_wrapper_keeps_false_memory_generation_in_effect_phase(self):
        anchor = _trace("rewrite")
        anchor.reconsolidate = Mock(return_value=True)

        def search(query, *, top_k):
            return [(0.9, anchor)] if query == "query" else []

        controller, memory, llm = _controller(search)
        llm.generate_text.return_value = (
            "a replacement memory with enough characters",
            {},
        )

        recalled = controller.recall("query")

        self.assertEqual(recalled, [anchor])
        self.assertEqual(
            anchor.content,
            "a replacement memory with enough characters",
        )
        memory.upsert_memory.assert_called_once_with(anchor)
        memory.update_memory.assert_not_called()
        llm.generate_text.assert_called_once()

    def test_force_local_stops_before_all_memory_reads(self):
        def forbidden_search(*_args, **_kwargs):
            raise AssertionError("force_local reached the embedder-backed store")

        controller, memory, llm = _controller(forbidden_search)

        plan = controller.build_recall_plan(
            "private query",
            now=5_000.0,
            force_local=True,
        )
        recalled = controller.recall("private query", force_local=True)

        self.assertEqual(plan.hits, ())
        self.assertEqual(recalled, [])
        memory.search_memories.assert_not_called()
        memory.chronological_recall.assert_not_called()
        memory.update_memory.assert_not_called()
        memory.upsert_memory.assert_not_called()
        llm.generate_text.assert_not_called()


if __name__ == "__main__":
    unittest.main()
