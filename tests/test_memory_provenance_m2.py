import copy
import json
import threading
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import Mock, mock_open, patch

from components.vector_store import MemoryStoreError
from core.engine.autonomous import AutonomousController
from core.engine.memory_ops import (
    MemoryHit,
    MemoryOperationsController,
    RecallPlan,
    _belief_delete_intent_id,
    _belief_merge_child_id,
)
from core.memory import MemoryTrace, MemoryType
from tests.dream_ledger_support import InMemoryOperationLedger
from core.memory_context import (
    MemoryPrivacy,
    MemoryScope,
    current_memory_context,
    interaction_memory_context,
    maintenance_memory_context,
    memory_context_scope,
)
from core.self_model import SelfModel


def _trace(
    record_id,
    *,
    scope="owner",
    privacy="standard",
    memory_type=MemoryType.EPISODIC,
    content=None,
    created_at=1.0,
):
    return MemoryTrace(
        id=record_id,
        content=content or f"memory {record_id}",
        type=memory_type,
        valence=0.0,
        arousal=0.2,
        importance=0.5,
        strength=0.2,
        created_at=created_at,
        scope=scope,
        privacy=privacy,
    )


class _RecordingMemory:
    def __init__(self, records):
        self.records = {trace.id: trace for trace in records}
        self.add_batches = []
        self.update_batches = []
        self.remove_batches = []
        self.write_contexts = []
        self.upgrade_calls = []

    def get_all(self):
        return list(self.records.values())

    def add_memories(self, traces):
        batch = list(traces)
        self.add_batches.append(batch)
        self.write_contexts.append(current_memory_context())
        for trace in batch:
            self.records[trace.id] = trace

    def update_memories(self, traces):
        batch = list(traces)
        self.update_batches.append(batch)
        self.write_contexts.append(current_memory_context())
        for trace in batch:
            self.records[trace.id] = trace

    def upgrade_legacy_provenance(self, trace):
        self.upgrade_calls.append(trace)
        self.write_contexts.append(current_memory_context())
        trace.origin_kind = "consolidation"
        trace.origin_source = "sleep"
        trace.source_event_id = None
        trace.provenance_parent_ids = list(trace.consolidation_parent_ids)
        self.records[trace.id] = trace
        return trace

    def remove_many(self, record_ids):
        batch = list(record_ids)
        self.remove_batches.append(batch)
        self.write_contexts.append(current_memory_context())
        for record_id in batch:
            self.records.pop(record_id, None)


def _controller(memory, response=None):
    controller = object.__new__(MemoryOperationsController)
    llm = SimpleNamespace(generate_text=Mock(return_value=(response or "[]", {})))
    controller.engine = SimpleNamespace(
        memory=memory,
        llm=llm,
        operation_ledger=InMemoryOperationLedger(),
    )
    return controller, llm


class RecallAndInteractionScopeTests(unittest.TestCase):
    def test_agent_recall_hit_is_returned_without_mutation(self):
        trace = _trace("agent-read", scope="agent")
        before = copy.deepcopy(trace.__dict__)
        memory = SimpleNamespace(update_memory=Mock(), upsert_memory=Mock())
        controller, _llm = _controller(memory)
        plan = RecallPlan(
            hits=(MemoryHit(0.9, trace),),
            mood=0.4,
            dynamic_top_k=1,
            return_limit=1,
            throttle_level="",
            chronological_error_type=None,
            force_local=False,
        )
        context = interaction_memory_context(
            source="web",
            request_id="request-1",
            private_ephemeral=False,
            local_only=False,
        )

        with memory_context_scope(context):
            recalled = controller.apply_recall_effects(plan)

        self.assertEqual(recalled, [trace])
        self.assertEqual(trace.__dict__, before)
        memory.update_memory.assert_not_called()
        memory.upsert_memory.assert_not_called()

    def test_owner_neighbour_search_is_explicitly_writable_only(self):
        neighbour = _trace("owner-neighbour")
        neighbour.is_flashbulb = True
        memory = SimpleNamespace(
            search_memories=Mock(return_value=[(0.9, neighbour)]),
            update_memory=Mock(),
            add_memory=Mock(),
            enforce_garbage_collection=Mock(),
        )
        controller, _llm = _controller(memory)
        controller.engine.ego = SimpleNamespace(get_active_beliefs=Mock(return_value=[]))
        controller.integrity_filter = SimpleNamespace(check_contradiction=Mock())

        controller.update_or_add_memory(
            "hello",
            {
                "internal_monologue": "thought",
                "valence": 0.1,
                "arousal": 0.2,
                "importance": 0.4,
            },
        )

        memory.search_memories.assert_called_once_with(
            "hello", top_k=1, writable_only=True
        )
        memory.update_memory.assert_called_once_with(neighbour)
        memory.add_memory.assert_not_called()

    def test_recall_store_failure_restores_the_entire_trace(self):
        trace = _trace("recall-rollback")
        trace.is_flashbulb = True
        before = copy.deepcopy(trace.__dict__)
        failure = MemoryStoreError("update_meta", cause_type="OSError")
        memory = SimpleNamespace(
            update_memory=Mock(side_effect=failure),
            upsert_memory=Mock(),
        )
        controller, _llm = _controller(memory)
        plan = RecallPlan(
            hits=(MemoryHit(0.9, trace),),
            mood=0.5,
            dynamic_top_k=1,
            return_limit=1,
            throttle_level="",
            chronological_error_type=None,
            force_local=False,
        )

        with self.assertRaises(MemoryStoreError):
            controller.apply_recall_effects(plan)

        self.assertEqual(trace.__dict__, before)

    def test_recall_rewrite_failure_restores_content_and_counters(self):
        trace = _trace("recall-rewrite-rollback")
        before = copy.deepcopy(trace.__dict__)
        failure = MemoryStoreError("upsert", cause_type="OSError")
        memory = SimpleNamespace(
            update_memory=Mock(),
            upsert_memory=Mock(side_effect=failure),
        )
        controller, llm = _controller(
            memory,
            "a replacement memory with enough characters",
        )
        plan = RecallPlan(
            hits=(MemoryHit(0.9, trace),),
            mood=1.0,
            dynamic_top_k=1,
            return_limit=1,
            throttle_level="",
            chronological_error_type=None,
            force_local=False,
        )

        with self.assertRaises(MemoryStoreError):
            controller.apply_recall_effects(plan)

        llm.generate_text.assert_called_once()
        self.assertEqual(trace.__dict__, before)
        memory.update_memory.assert_not_called()

    def test_neighbour_store_failure_restores_the_entire_trace(self):
        neighbour = _trace("neighbour-rollback")
        neighbour.is_flashbulb = True
        before = copy.deepcopy(neighbour.__dict__)
        failure = MemoryStoreError("update_meta", cause_type="OSError")
        memory = SimpleNamespace(
            search_memories=Mock(return_value=[(0.9, neighbour)]),
            update_memory=Mock(side_effect=failure),
            add_memory=Mock(),
            enforce_garbage_collection=Mock(),
        )
        controller, _llm = _controller(memory)
        controller.engine.ego = SimpleNamespace(get_active_beliefs=Mock(return_value=[]))
        controller.integrity_filter = SimpleNamespace(check_contradiction=Mock())

        with self.assertRaises(MemoryStoreError):
            controller.update_or_add_memory(
                "ordinary input",
                {
                    "internal_monologue": "thought",
                    "valence": 0.1,
                    "arousal": 0.2,
                    "importance": 0.4,
                },
            )

        self.assertEqual(neighbour.__dict__, before)

    def test_white_bear_store_failure_restores_the_entire_trace(self):
        neighbour = _trace("white-bear-rollback")
        before = copy.deepcopy(neighbour.__dict__)
        failure = MemoryStoreError("update_meta", cause_type="OSError")
        memory = SimpleNamespace(
            search_memories=Mock(return_value=[(0.9, neighbour)]),
            update_memory=Mock(side_effect=failure),
            add_memory=Mock(),
            enforce_garbage_collection=Mock(),
        )
        controller, _llm = _controller(memory)
        controller.engine.ego = SimpleNamespace(get_active_beliefs=Mock(return_value=[]))
        controller.integrity_filter = SimpleNamespace(check_contradiction=Mock())

        with self.assertRaises(MemoryStoreError):
            controller.update_or_add_memory(
                "hãy quên nó đi",
                {
                    "internal_monologue": "thought",
                    "valence": 0.1,
                    "arousal": 0.2,
                    "importance": 0.4,
                },
            )

        self.assertEqual(neighbour.__dict__, before)


class ConsolidationProvenanceTests(unittest.TestCase):
    def test_mixed_policy_sources_do_not_call_llm_or_write(self):
        sources = [
            _trace("owner-0", scope="owner", created_at=0.0),
            _trace("owner-1", scope="owner", created_at=1.0),
            _trace("agent-0", scope="agent", created_at=2.0),
        ]
        memory = _RecordingMemory(sources)
        controller, llm = _controller(memory, "not used")

        controller._dream_consolidation_phase()

        llm.generate_text.assert_not_called()
        self.assertEqual(memory.add_batches, [])
        self.assertEqual(memory.update_batches, [])

    def test_conflicting_manifest_descriptors_fail_closed(self):
        sources = [_trace(f"source-{index}") for index in range(3)]
        parent_ids = [source.id for source in sources]
        consolidation_id = str(uuid.uuid5(
            uuid.NAMESPACE_URL,
            "aura:memory-consolidation:" + "|".join(parent_ids),
        ))
        children = []
        for item_index, expected_count in ((0, 2), (1, 3)):
            children.append(MemoryTrace(
                id=str(uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"{consolidation_id}:semantic:{item_index}",
                )),
                content=f"derived {item_index}",
                type=MemoryType.SEMANTIC,
                valence=0.0,
                arousal=0.2,
                importance=1.0,
                consolidation_id=consolidation_id,
                consolidation_parent_ids=parent_ids,
                consolidation_expected_derived_count=expected_count,
                origin_kind="consolidation",
                origin_source="sleep",
                provenance_parent_ids=parent_ids,
            ))
        memory = _RecordingMemory(sources + children)
        controller, llm = _controller(memory, "not used")

        controller._dream_consolidation_phase()

        llm.generate_text.assert_not_called()
        self.assertEqual(memory.add_batches, [])
        self.assertEqual(memory.update_batches, [])

    def test_children_inherit_agent_policy_and_both_lineages(self):
        sources = [
            _trace(f"agent-{index}", scope="agent", created_at=float(index))
            for index in range(3)
        ]
        memory = _RecordingMemory(sources)
        response = json.dumps([{
            "tags": ["stable"],
            "reasoning": "shared pattern",
            "conclusion": "durable conclusion",
        }])
        controller, _llm = _controller(memory, response)

        with memory_context_scope(maintenance_memory_context(
            origin_kind="sleep",
            origin_source="test",
        )):
            controller._dream_consolidation_phase()

        self.assertEqual(len(memory.add_batches), 1)
        parent_ids = [source.id for source in sources]
        for child in memory.add_batches[0]:
            self.assertEqual(child.scope, "agent")
            self.assertEqual(child.privacy, "standard")
            self.assertEqual(child.origin_kind, "consolidation")
            self.assertEqual(child.origin_source, "sleep")
            self.assertEqual(child.consolidation_parent_ids, parent_ids)
            self.assertEqual(child.provenance_parent_ids, parent_ids)
        self.assertEqual(memory.write_contexts[0].write_scope, MemoryScope.AGENT)

    def test_complete_m21_manifest_is_upgraded_before_sources_are_marked(self):
        sources = [_trace(f"source-{index}") for index in range(3)]
        parent_ids = [source.id for source in sources]
        consolidation_id = str(uuid.uuid5(
            uuid.NAMESPACE_URL,
            "aura:memory-consolidation:" + "|".join(parent_ids),
        ))
        derived = [
            MemoryTrace(
                id=str(uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"{consolidation_id}:{kind}:0",
                )),
                content=f"legacy {kind}",
                type=(MemoryType.SEMANTIC if kind == "semantic" else MemoryType.CORE),
                valence=0.0,
                arousal=0.2,
                importance=1.0,
                consolidation_id=consolidation_id,
                consolidation_parent_ids=parent_ids,
                consolidation_expected_derived_count=2,
            )
            for kind in ("semantic", "core")
        ]
        memory = _RecordingMemory(sources + derived)
        controller, llm = _controller(memory, "not used")

        controller._dream_consolidation_phase()

        llm.generate_text.assert_not_called()
        self.assertEqual(memory.upgrade_calls, derived)
        self.assertEqual(len(memory.update_batches), 1)
        self.assertEqual(memory.update_batches[0], sources)
        self.assertTrue(all(
            trace.origin_kind == "consolidation"
            and trace.provenance_parent_ids == parent_ids
            for trace in derived
        ))
        self.assertTrue(all(source.is_consolidated_source for source in sources))


class DerivedBeliefProvenanceTests(unittest.TestCase):
    def test_reappraisal_inherits_single_parent_policy(self):
        attempt_id = "aee5c8c3-d2ac-4e39-b714-a21b1b7a6d30"
        parent = _trace(
            "agent-contradiction",
            scope="agent",
            content="contradiction",
        )
        parent.overlays = [f"[ToReevaluate:{attempt_id}]"]
        records = [parent]
        added = []
        contexts = []

        def add_memory(trace):
            records.append(trace)
            added.append(trace)
            contexts.append(current_memory_context())

        memory = SimpleNamespace(
            get_all=Mock(side_effect=lambda: list(records)),
            add_memory=Mock(side_effect=add_memory),
            upsert_memory=Mock(),
            update_memory=Mock(),
        )
        controller = object.__new__(MemoryOperationsController)
        controller.engine = SimpleNamespace(
            memory=memory,
            ego=SimpleNamespace(get_active_beliefs=Mock(return_value=[])),
            llm=SimpleNamespace(generate_text=Mock(return_value=(json.dumps({
                "action": "EVOLVE",
                "reasoning": "new evidence",
                "new_belief": "refined belief",
            }), {}))),
            operation_ledger=InMemoryOperationLedger(),
        )

        with patch("builtins.print"), memory_context_scope(
            maintenance_memory_context(
                origin_kind="sleep",
                origin_source="test",
            )
        ):
            controller._cognitive_reappraisal_phase()

        self.assertEqual(len(added), 1)
        child = added[0]
        self.assertEqual((child.scope, child.privacy), ("agent", "standard"))
        self.assertEqual(child.origin_kind, "reappraisal")
        self.assertEqual(child.provenance_parent_ids, [parent.id])
        self.assertEqual(contexts[0].write_scope, MemoryScope.AGENT)

    def test_reappraisal_durable_child_finishes_cleanup_without_llm(self):
        parent = _trace(
            "retry-parent",
            content="[ToReevaluate] contradiction",
        )
        child_id = str(uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"aura:reappraisal:{parent.id}",
        ))
        child = MemoryTrace(
            id=child_id,
            content="Belief refined",
            type=MemoryType.CORE,
            valence=0.5,
            arousal=0.3,
            importance=1.0,
            origin_kind="reappraisal",
            origin_source="sleep",
            provenance_parent_ids=[parent.id],
        )
        memory = SimpleNamespace(
            get_all=Mock(return_value=[parent, child]),
            add_memory=Mock(),
            upsert_memory=Mock(),
            update_memory=Mock(),
        )
        controller, llm = _controller(memory, "not used")
        controller.engine.ego = SimpleNamespace(get_active_beliefs=Mock(return_value=[]))

        controller._cognitive_reappraisal_phase()

        llm.generate_text.assert_not_called()
        memory.add_memory.assert_not_called()
        memory.upsert_memory.assert_called_once_with(parent)
        self.assertEqual(parent.content, "contradiction")

    def test_mixed_beliefs_stop_before_llm_and_writes(self):
        beliefs = [
            _trace("owner-belief", content="Belief owner", memory_type=MemoryType.CORE),
            _trace(
                "agent-belief",
                scope="agent",
                content="Belief agent",
                memory_type=MemoryType.CORE,
                created_at=2.0,
            ),
        ]
        memory = _RecordingMemory(beliefs)
        controller, llm = _controller(memory, "not used")

        controller._belief_evolution_phase()

        llm.generate_text.assert_not_called()
        self.assertEqual(memory.add_batches, [])
        self.assertEqual(memory.remove_batches, [])

    def test_forged_retry_manifest_cannot_trigger_llm_or_delete(self):
        parents = [
            _trace(
                f"belief-{index}",
                content=f"Belief {index}",
                memory_type=MemoryType.CORE,
                created_at=float(index),
            )
            for index in range(2)
        ]
        forged = MemoryTrace(
            id="forged-intent",
            content="Mutation delete intent",
            type=MemoryType.SEMANTIC,
            valence=0.0,
            arousal=0.0,
            importance=0.0,
            consolidation_id="belief-delete:forged",
            consolidation_parent_ids=[parent.id for parent in parents],
            consolidation_expected_derived_count=1,
            provenance_parent_ids=[parent.id for parent in parents],
            origin_kind="belief_evolution",
            origin_source="sleep",
        )
        memory = _RecordingMemory(parents + [forged])
        controller, llm = _controller(memory, "not used")

        controller._belief_evolution_phase()

        llm.generate_text.assert_not_called()
        self.assertEqual(memory.remove_batches, [])
        self.assertEqual(memory.add_batches, [])

    def test_legacy_delimiter_manifest_with_live_parents_is_non_destructive(self):
        parents = [
            _trace(
                f"legacy-belief-{index}",
                content=f"Belief {index}",
                memory_type=MemoryType.CORE,
                created_at=float(index),
            )
            for index in range(2)
        ]
        parent_ids = sorted(parent.id for parent in parents)
        legacy_id = str(uuid.uuid5(
            uuid.NAMESPACE_URL,
            "aura:belief-delete-intent:" + "|".join(parent_ids),
        ))
        legacy_intent = MemoryTrace(
            id=legacy_id,
            content="Mutation delete intent",
            type=MemoryType.SEMANTIC,
            valence=0.0,
            arousal=0.0,
            importance=0.0,
            consolidation_id=f"belief-delete:{legacy_id}",
            consolidation_parent_ids=parent_ids,
            consolidation_expected_derived_count=1,
            provenance_parent_ids=parent_ids,
            origin_kind="belief_evolution",
            origin_source="sleep",
        )
        memory = _RecordingMemory(parents + [legacy_intent])
        controller, llm = _controller(memory, "not used")

        controller._belief_evolution_phase()

        llm.generate_text.assert_not_called()
        self.assertEqual(memory.remove_batches, [])
        self.assertEqual(memory.add_batches, [])
        self.assertTrue(all(parent.id in memory.records for parent in parents))

    def test_belief_batch_is_atomic_and_carries_exact_lineage(self):
        parents = [
            _trace(
                f"belief-{index}",
                content=f"Belief {index}",
                memory_type=MemoryType.CORE,
                created_at=float(index),
            )
            for index in range(2)
        ]
        memory = _RecordingMemory(parents)
        response = json.dumps({
            "analysis": "merge",
            "resolutions": [{
                "type": "MERGE",
                "indices": [0, 1],
                "new_content": "mature belief",
            }],
        })
        controller, _llm = _controller(memory, response)

        with patch("builtins.print"), patch("os.makedirs"), patch(
            "core.engine.memory_ops.open", mock_open(), create=True
        ):
            controller._belief_evolution_phase()

        parent_ids = [parent.id for parent in parents]
        self.assertEqual(len(memory.add_batches), 1)
        self.assertEqual(len(memory.add_batches[0]), 2)
        for child in memory.add_batches[0]:
            self.assertEqual((child.scope, child.privacy), ("owner", "standard"))
            self.assertEqual(child.origin_kind, "belief_evolution")
            self.assertEqual(child.provenance_parent_ids, parent_ids)
            self.assertEqual(child.consolidation_expected_derived_count, 2)
        self.assertEqual(memory.remove_batches, [parent_ids])

    def test_delimiter_ambiguous_parent_groups_get_distinct_manifests(self):
        parent_specs = (
            ("a", 0.0),
            ("b|c", 1.0),
            ("a|b", 2.0),
            ("c", 3.0),
        )
        parents = [
            _trace(
                record_id,
                content=f"Belief {record_id}",
                memory_type=MemoryType.CORE,
                created_at=created_at,
            )
            for record_id, created_at in parent_specs
        ]
        memory = _RecordingMemory(parents)
        response = json.dumps({
            "analysis": "two disjoint merges",
            "resolutions": [
                {
                    "type": "MERGE",
                    "indices": [0, 1],
                    "new_content": "same replacement",
                },
                {
                    "type": "MERGE",
                    "indices": [2, 3],
                    "new_content": "same replacement",
                },
            ],
        })
        controller, _llm = _controller(memory, response)

        with patch("builtins.print"), patch("os.makedirs"), patch(
            "core.engine.memory_ops.open", mock_open(), create=True
        ):
            controller._belief_evolution_phase()

        durable_merges = [
            trace for trace in memory.records.values()
            if trace.consolidation_id.startswith("belief-merge:")
        ]
        durable_intents = [
            trace for trace in memory.records.values()
            if trace.consolidation_id.startswith("belief-delete:")
        ]
        expected_groups = {
            tuple(sorted(("a", "b|c"))),
            tuple(sorted(("a|b", "c"))),
        }
        self.assertEqual(len(memory.add_batches), 1)
        self.assertEqual(len(memory.add_batches[0]), 4)
        self.assertEqual(len(durable_merges), 2)
        self.assertEqual(len(durable_intents), 2)
        self.assertEqual(
            {tuple(trace.consolidation_parent_ids) for trace in durable_merges},
            expected_groups,
        )
        self.assertEqual(
            {tuple(trace.consolidation_parent_ids) for trace in durable_intents},
            expected_groups,
        )
        self.assertEqual(
            memory.remove_batches,
            [sorted(parent.id for parent in parents)],
        )

    def test_canonical_delete_intent_retries_only_remaining_parent(self):
        parents = [
            _trace(
                f"partial-belief-{index}",
                content=f"Belief {index}",
                memory_type=MemoryType.CORE,
                created_at=float(index),
            )
            for index in range(2)
        ]
        parent_ids = sorted(parent.id for parent in parents)
        intent_id = _belief_delete_intent_id(parent_ids)
        intent = MemoryTrace(
            id=intent_id,
            content="Mutation delete intent",
            type=MemoryType.SEMANTIC,
            valence=0.0,
            arousal=0.0,
            importance=0.0,
            consolidation_id=f"belief-delete:{intent_id}",
            consolidation_parent_ids=parent_ids,
            consolidation_expected_derived_count=1,
            origin_kind="belief_evolution",
            origin_source="sleep",
            provenance_parent_ids=parent_ids,
        )
        memory = _RecordingMemory([parents[1], intent])
        controller, llm = _controller(memory, "not used")

        controller._belief_evolution_phase()

        llm.generate_text.assert_not_called()
        self.assertEqual(memory.remove_batches, [[parents[1].id]])

    def test_historical_merge_child_remains_eligible_for_evolution(self):
        missing_parent_ids = ["gone-a", "gone-b"]
        merge_id = str(uuid.uuid5(
            uuid.NAMESPACE_URL,
            "aura:belief-merge:gone-a|gone-b:mature",
        ))
        merged = MemoryTrace(
            id=merge_id,
            content="Niềm tin cốt lõi (Belief): mature",
            type=MemoryType.CORE,
            valence=0.5,
            arousal=0.2,
            importance=1.0,
            consolidation_id=f"belief-merge:{merge_id}",
            consolidation_parent_ids=missing_parent_ids,
            consolidation_expected_derived_count=1,
            origin_kind="belief_evolution",
            origin_source="sleep",
            provenance_parent_ids=missing_parent_ids,
        )
        peer = _trace(
            "peer-belief",
            content="Belief peer",
            memory_type=MemoryType.CORE,
            created_at=2.0,
        )
        memory = _RecordingMemory([merged, peer])
        controller, llm = _controller(
            memory,
            json.dumps({"analysis": "stable", "resolutions": []}),
        )

        with patch("builtins.print"):
            controller._belief_evolution_phase()

        llm.generate_text.assert_called_once()

    def test_manifest_framing_handles_unpaired_unicode_surrogates(self):
        parent_ids = ["belief-\ud800", "belief-b"]

        intent_id = _belief_delete_intent_id(parent_ids)
        merge_id = _belief_merge_child_id(
            parent_ids,
            "replacement-\udfff",
        )

        self.assertEqual(len(uuid.UUID(intent_id).bytes), 16)
        self.assertEqual(len(uuid.UUID(merge_id).bytes), 16)
        self.assertNotEqual(intent_id, merge_id)

    def test_partial_two_merge_batch_never_deletes_unreplaced_parents(self):
        class PartialBatchMemory(_RecordingMemory):
            def __init__(self, records):
                super().__init__(records)
                self.fail_once = True
                self.persisted_merge_parent_ids = []

            def add_memories(self, traces):
                batch = list(traces)
                self.add_batches.append(batch)
                self.write_contexts.append(current_memory_context())
                if self.fail_once:
                    self.fail_once = False
                    merges = [
                        trace for trace in batch
                        if trace.consolidation_id.startswith("belief-merge:")
                    ]
                    intents = [
                        trace for trace in batch
                        if trace.consolidation_id.startswith("belief-delete:")
                    ]
                    persisted_merges = merges[:1]
                    self.persisted_merge_parent_ids = list(
                        persisted_merges[0].consolidation_parent_ids
                    )
                    for trace in persisted_merges + intents:
                        self.records[trace.id] = trace
                    raise MemoryStoreError(
                        "add_batch",
                        record_count=len(batch),
                        cause_type="PartialWrite",
                    )
                super().add_memories(batch)

        parents = [
            _trace(
                f"two-merge-{index}",
                content=f"Belief {index}",
                memory_type=MemoryType.CORE,
                created_at=float(index),
            )
            for index in range(4)
        ]
        memory = PartialBatchMemory(parents)
        response = json.dumps({
            "analysis": "two merges",
            "resolutions": [
                {
                    "type": "MERGE",
                    "indices": [0, 1],
                    "new_content": "first replacement",
                },
                {
                    "type": "MERGE",
                    "indices": [2, 3],
                    "new_content": "second replacement",
                },
            ],
        })
        controller, llm = _controller(memory, response)

        with patch("builtins.print"), patch("os.makedirs"), patch(
            "core.engine.memory_ops.open", mock_open(), create=True
        ):
            with self.assertRaises(MemoryStoreError):
                controller._belief_evolution_phase()
            llm.generate_text.reset_mock()
            controller._belief_evolution_phase()

        llm.generate_text.assert_not_called()
        parent_ids = sorted(parent.id for parent in parents)
        self.assertEqual(memory.remove_batches, [parent_ids])
        self.assertTrue(all(parent.id not in memory.records for parent in parents))
        durable_merges = [
            trace for trace in memory.records.values()
            if trace.consolidation_id.startswith("belief-merge:")
        ]
        self.assertEqual(len(durable_merges), 2)

    def test_overlapping_live_intents_fail_closed(self):
        parents = [
            _trace(
                f"overlap-belief-{index}",
                content=f"Belief {index}",
                memory_type=MemoryType.CORE,
                created_at=float(index),
            )
            for index in range(3)
        ]
        intents = []
        for group in ((parents[0], parents[1]), (parents[1], parents[2])):
            parent_ids = sorted(parent.id for parent in group)
            intent_id = _belief_delete_intent_id(parent_ids)
            intents.append(MemoryTrace(
                id=intent_id,
                content="Mutation delete intent",
                type=MemoryType.SEMANTIC,
                valence=0.0,
                arousal=0.0,
                importance=0.0,
                consolidation_id=f"belief-delete:{intent_id}",
                consolidation_parent_ids=parent_ids,
                consolidation_expected_derived_count=1,
                origin_kind="belief_evolution",
                origin_source="sleep",
                provenance_parent_ids=parent_ids,
            ))
        memory = _RecordingMemory(parents + intents)
        controller, llm = _controller(memory, "not used")

        controller._belief_evolution_phase()

        llm.generate_text.assert_not_called()
        self.assertEqual(memory.remove_batches, [])
        self.assertTrue(all(parent.id in memory.records for parent in parents))


class AgentOriginTests(unittest.TestCase):
    def test_self_model_seeds_are_agent_owned(self):
        contexts = []
        added = []

        def get_all():
            contexts.append(current_memory_context())
            return []

        manager = SimpleNamespace(
            get_all=Mock(side_effect=get_all),
            add_memory=Mock(side_effect=lambda trace: added.append(trace)),
        )
        model = SelfModel(memory_manager=manager)

        with patch("builtins.print"):
            model.init_core_semantics()

        self.assertEqual(contexts[0].read_scopes, (MemoryScope.AGENT,))
        self.assertEqual(len(added), 3)
        self.assertTrue(all(
            trace.scope == "agent"
            and trace.origin_kind == "seed"
            and trace.origin_source == "self_model"
            for trace in added
        ))

    def test_reading_memory_is_agent_owned_in_agent_write_context(self):
        added = []
        contexts = []

        def add_memory(trace):
            added.append(trace)
            contexts.append(current_memory_context())

        autonomous = object.__new__(AutonomousController)
        autonomous.engine = SimpleNamespace(
            reader=SimpleNamespace(
                get_next_reading_material=Mock(return_value=("chapter", "content"))
            ),
            ego=SimpleNamespace(get_bio_state_dict=Mock(return_value={})),
            llm=SimpleNamespace(generate_text=Mock(return_value=("summary", {}))),
            memory=SimpleNamespace(add_memory=Mock(side_effect=add_memory)),
        )

        with patch("builtins.print"):
            autonomous._do_reading_session()

        self.assertEqual(len(added), 1)
        self.assertEqual((added[0].scope, added[0].privacy), ("agent", "standard"))
        self.assertEqual(added[0].origin_kind, "reading")
        self.assertEqual(contexts[0].write_scope, MemoryScope.AGENT)


if __name__ == "__main__":
    unittest.main()
