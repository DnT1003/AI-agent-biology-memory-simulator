import json
import copy
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, mock_open, patch

from components.vector_store import MemoryStoreError, VectorStore
from core.engine.memory_ops import (
    MemoryOperationsController,
    _belief_merge_child_id,
)
from core.memory import MemoryManager, MemoryTrace, MemoryType
from tests.dream_ledger_support import InMemoryOperationLedger


def _trace(
    record_id: str,
    *,
    strength: float = 0.2,
    created_at: float = 1_000.0,
    last_decayed_at: float = 1_000.0,
) -> MemoryTrace:
    return MemoryTrace(
        id=record_id,
        content=f"source-{record_id}",
        type=MemoryType.EPISODIC,
        valence=0.0,
        arousal=0.2,
        importance=0.5,
        strength=strength,
        created_at=created_at,
        last_recalled=created_at,
        last_decayed_at=last_decayed_at,
    )


class _FailingCollection:
    def __getattr__(self, _name):
        def fail(*_args, **_kwargs):
            raise RuntimeError("secret-payload-must-not-be-logged")

        return fail


class VectorStoreWriteContractTests(unittest.TestCase):
    def setUp(self):
        self.store = object.__new__(VectorStore)
        self.store.collection = _FailingCollection()
        self.store.client = _FailingCollection()
        self.meta = _trace("private-record-id")

    def test_all_guarded_writes_raise_metadata_safe_typed_error(self):
        operations = (
            ("add", lambda: self.store.add("private-record-id", [0.1], self.meta)),
            ("add_batch", lambda: self.store.add_batch(["private-record-id"], [[0.1]], [self.meta])),
            ("update_meta", lambda: self.store.update_meta("private-record-id", self.meta)),
            ("update_meta_batch", lambda: self.store.update_meta_batch(["private-record-id"], [self.meta])),
            ("update_vector", lambda: self.store.update_vector("private-record-id", [0.1])),
            ("remove", lambda: self.store.remove("private-record-id")),
            ("remove_batch", lambda: self.store.remove_batch(["private-record-id"])),
            ("clear_all", self.store.clear_all),
        )

        for expected_operation, action in operations:
            with self.subTest(operation=expected_operation), patch(
                "components.vector_store.logger.error"
            ) as log_error:
                with self.assertRaises(MemoryStoreError) as raised:
                    action()
                error = raised.exception
                self.assertEqual(error.operation, expected_operation)
                self.assertEqual(error.cause_type, "RuntimeError")
                rendered = str(error)
                self.assertNotIn("private-record-id", rendered)
                self.assertNotIn("secret-payload", rendered)
                log_args = log_error.call_args.args
                logged = str(log_args[0]) % tuple(log_args[1:])
                self.assertNotIn("private-record-id", logged)
                self.assertNotIn("secret-payload", logged)

    def test_upsert_sends_vector_and_metadata_in_one_collection_call(self):
        collection = Mock()
        store = object.__new__(VectorStore)
        store.collection = collection

        store.upsert("record-1", [0.25, 0.75], self.meta)

        collection.upsert.assert_called_once()
        kwargs = collection.upsert.call_args.kwargs
        self.assertEqual(kwargs["ids"], ["record-1"])
        self.assertEqual(kwargs["embeddings"], [[0.25, 0.75]])
        self.assertEqual(len(kwargs["metadatas"]), 1)
        collection.update.assert_not_called()

    def test_weak_memory_gc_retains_consolidated_sources(self):
        collection = Mock()
        ordinary = _trace("ordinary", strength=0.01)
        source = _trace("source", strength=0.01)
        source.is_consolidated_source = True
        store = object.__new__(VectorStore)
        store.collection = collection
        collection.get.return_value = {
            "ids": ["ordinary", "source"],
            "metadatas": [
                store._obj_to_dict(ordinary),
                store._obj_to_dict(source),
            ],
        }

        self.assertEqual(store.delete_weak_memories(), 1)
        manifest_where = collection.get.call_args_list[1].kwargs["where"]
        self.assertIn(
            {"consolidation_parent_ids": {"$ne": "[]"}},
            manifest_where["$and"],
        )
        delete_kwargs = collection.delete.call_args.kwargs
        self.assertEqual(delete_kwargs["ids"], ["ordinary"])
        self.assertIn("where", delete_kwargs)

    def test_weak_memory_delete_failure_is_typed_and_safe(self):
        collection = Mock()
        store = object.__new__(VectorStore)
        store.collection = collection
        trace = _trace("private-record-id", strength=0.01)
        collection.get.return_value = {
            "ids": ["private-record-id"],
            "metadatas": [store._obj_to_dict(trace)],
        }
        collection.delete.side_effect = RuntimeError(
            "secret-payload-must-not-be-logged"
        )
        with patch("components.vector_store.logger.error") as log_error:
            with self.assertRaises(MemoryStoreError) as raised:
                store.delete_weak_memories()

        self.assertEqual(raised.exception.operation, "delete_weak_memories")
        log_args = log_error.call_args.args
        rendered = str(log_args[0]) % tuple(log_args[1:])
        self.assertNotIn("private-record-id", rendered)
        self.assertNotIn("secret-payload", rendered)

    def test_gc_retains_unmarked_parent_referenced_by_durable_manifest(self):
        collection = Mock()
        store = object.__new__(VectorStore)
        store.collection = collection
        pending_parent = _trace("pending-parent", strength=0.01)
        ordinary = _trace("ordinary", strength=0.01)
        derived = _trace("derived", strength=1.0)
        derived.consolidation_parent_ids = ["pending-parent"]
        collection.get.side_effect = [
            {
                "ids": ["pending-parent", "ordinary"],
                "metadatas": [
                    store._obj_to_dict(pending_parent),
                    store._obj_to_dict(ordinary),
                ],
            },
            {
                "ids": ["derived"],
                "metadatas": [store._obj_to_dict(derived)],
            },
        ]

        self.assertEqual(store.delete_weak_memories(), 1)
        delete_kwargs = collection.delete.call_args.kwargs
        self.assertEqual(delete_kwargs["ids"], ["ordinary"])
        self.assertIn("where", delete_kwargs)

    def test_gc_aborts_if_manifest_scan_response_is_malformed(self):
        collection = Mock()
        store = object.__new__(VectorStore)
        store.collection = collection
        weak = _trace("weak", strength=0.01)
        collection.get.side_effect = [
            {
                "ids": ["weak"],
                "metadatas": [store._obj_to_dict(weak)],
            },
            {},
        ]

        with self.assertRaises(MemoryStoreError):
            store.delete_weak_memories()
        collection.delete.assert_not_called()

    def test_reset_collection_delete_and_recreate_failures_are_typed(self):
        cases = (
            (
                "reset_collection.delete",
                SimpleNamespace(
                    delete_collection=Mock(
                        side_effect=RuntimeError("secret delete failure")
                    ),
                    get_or_create_collection=Mock(),
                ),
            ),
            (
                "reset_collection.recreate",
                SimpleNamespace(
                    delete_collection=Mock(),
                    get_or_create_collection=Mock(
                        side_effect=RuntimeError("secret recreate failure")
                    ),
                ),
            ),
        )
        for expected_operation, client in cases:
            with self.subTest(operation=expected_operation):
                store = object.__new__(VectorStore)
                store.client = client
                with patch("builtins.print"), patch(
                    "components.vector_store.logger.error"
                ) as log_error:
                    with self.assertRaises(MemoryStoreError) as raised:
                        store.reset_collection()

                self.assertEqual(raised.exception.operation, expected_operation)
                log_args = log_error.call_args.args
                rendered = str(log_args[0]) % tuple(log_args[1:])
                self.assertNotIn("secret", rendered)

    def test_lineage_manifest_roundtrips_and_private_flags_do_not_serialize(self):
        store = object.__new__(VectorStore)
        trace = _trace("derived")
        trace.consolidation_id = "batch-1"
        trace.consolidation_parent_ids = ["source-b", "source-a"]
        trace.consolidation_expected_derived_count = 2
        trace._last_decay_checkpoint_pending = True

        metadata = store._obj_to_dict(trace)
        restored = store._dict_to_obj(metadata)

        self.assertNotIn("_last_decay_checkpoint_pending", metadata)
        self.assertEqual(
            restored.consolidation_parent_ids,
            ["source-b", "source-a"],
        )
        self.assertEqual(restored.consolidation_expected_derived_count, 2)
        self.assertEqual(restored.consolidation_id, "batch-1")

    def test_gc_get_and_get_all_failures_are_typed_and_safe(self):
        collection = Mock()
        collection.get.side_effect = RuntimeError("secret-read-payload")
        store = object.__new__(VectorStore)
        store.collection = collection

        for operation, action in (
            ("delete_weak_memories.get", store.delete_weak_memories),
            ("get_all_metadata", store.get_all_metadata),
        ):
            with self.subTest(operation=operation), patch(
                "components.vector_store.logger.error"
            ) as log_error:
                with self.assertRaises(MemoryStoreError) as raised:
                    action()
                self.assertEqual(raised.exception.operation, operation)
                log_args = log_error.call_args.args
                rendered = str(log_args[0]) % tuple(log_args[1:])
                self.assertNotIn("secret-read-payload", rendered)


class MemoryManagerWriteContractTests(unittest.TestCase):
    def test_manager_propagates_typed_add_failure(self):
        manager = object.__new__(MemoryManager)
        manager.lock = threading.RLock()
        manager.embedder = SimpleNamespace(encode=lambda _content: [0.2])
        failure = MemoryStoreError("upsert", cause_type="RuntimeError")
        manager.store = SimpleNamespace(
            supports_memory_access_policy=True,
            migrate_legacy_metadata=Mock(return_value=0),
            add_scoped=Mock(side_effect=failure),
        )

        with self.assertRaises(MemoryStoreError) as raised:
            manager.add_memory(_trace("record-1"))

        self.assertIs(raised.exception, failure)

    def test_embed_failure_is_typed_and_never_logs_content_or_message(self):
        manager = object.__new__(MemoryManager)
        manager.lock = threading.RLock()
        manager.embedder = SimpleNamespace(
            encode=Mock(side_effect=RuntimeError("secret-content server failure"))
        )
        manager.store = SimpleNamespace(
            supports_memory_access_policy=True,
            migrate_legacy_metadata=Mock(return_value=0),
            add_scoped=Mock(),
        )
        trace = _trace("record-1")
        trace.content = "secret-content"
        safe_logger = Mock()

        with patch("core.logger.get_logger", return_value=safe_logger):
            with self.assertRaises(MemoryStoreError) as raised:
                manager.add_memory(trace)

        self.assertEqual(raised.exception.operation, "embed")
        self.assertEqual(raised.exception.cause_type, "RuntimeError")
        log_args = safe_logger.error.call_args.args
        rendered = str(log_args[0]) % tuple(log_args[1:])
        self.assertNotIn("secret-content", rendered)
        self.assertNotIn("server failure", rendered)
        manager.store.add_scoped.assert_not_called()

    def test_content_upsert_uses_one_store_operation(self):
        manager = object.__new__(MemoryManager)
        manager.lock = threading.RLock()
        manager.embedder = SimpleNamespace(encode=lambda content: (len(content),))
        manager.store = SimpleNamespace(
            supports_memory_access_policy=True,
            migrate_legacy_metadata=Mock(return_value=0),
            upsert_scoped=Mock(
                side_effect=lambda _id, _vector, value, **_kwargs: value
            ),
        )
        trace = _trace("record-1")
        trace.content = "replacement"

        manager.upsert_memory(trace)

        manager.store.upsert_scoped.assert_called_once_with(
            "record-1",
            (len("replacement"),),
            trace,
            allowed_scopes=("owner",),
            require_existing=True,
        )

    def test_group_apis_use_one_store_call_each(self):
        manager = object.__new__(MemoryManager)
        manager.lock = threading.RLock()
        manager.embedder = SimpleNamespace(encode=lambda content: (len(content),))
        manager.store = SimpleNamespace(
            supports_memory_access_policy=True,
            migrate_legacy_metadata=Mock(return_value=0),
            add_batch_scoped=Mock(
                side_effect=lambda _ids, _vectors, values, **_kwargs: values
            ),
            update_meta_batch_scoped=Mock(
                side_effect=lambda _ids, values, **_kwargs: values
            ),
            remove_batch_scoped=Mock(),
        )
        traces = [_trace("one"), _trace("two")]

        manager.add_memories(traces)
        manager.update_memories(traces)
        manager.remove_many(["one", "two", "one"])

        manager.store.add_batch_scoped.assert_called_once()
        manager.store.update_meta_batch_scoped.assert_called_once_with(
            ["one", "two"],
            traces,
            allowed_scopes=("owner",),
        )
        manager.store.remove_batch_scoped.assert_called_once_with(
            ["one", "two"],
            allowed_scopes=("owner",),
        )


class _FakeMemoryManager:
    def __init__(
        self,
        sources,
        *,
        fail_add_batch=False,
        fail_update_batch=False,
        fail_remove_batch=False,
    ):
        self.records = {trace.id: trace for trace in sources}
        self.added = []
        self.updated = []
        self.add_batches = []
        self.update_batches = []
        self.remove_batches = []
        self.fail_add_batch = fail_add_batch
        self.fail_update_batch = fail_update_batch
        self.fail_remove_batch = fail_remove_batch
        self.store = SimpleNamespace(remove=Mock())

    def get_all(self):
        return list(self.records.values())

    def add_memory(self, trace):
        self.records[trace.id] = trace
        self.added.append(trace)

    def add_memories(self, traces):
        batch = list(traces)
        if self.fail_add_batch:
            raise MemoryStoreError(
                "add_batch", record_count=len(batch), cause_type="OSError"
            )
        self.add_batches.append(batch)
        for trace in batch:
            self.records[trace.id] = trace
            self.added.append(trace)

    def update_memory(self, trace):
        self.records[trace.id] = trace
        self.updated.append(trace)

    def update_memories(self, traces):
        batch = list(traces)
        if self.fail_update_batch:
            raise MemoryStoreError(
                "update_meta_batch",
                record_count=len(batch),
                cause_type="OSError",
            )
        self.update_batches.append(batch)
        for trace in batch:
            self.records[trace.id] = trace
            self.updated.append(trace)

    def upgrade_legacy_provenance(self, trace):
        trace.origin_kind = "consolidation"
        trace.origin_source = "sleep"
        trace.source_event_id = None
        trace.provenance_parent_ids = list(trace.consolidation_parent_ids)
        self.records[trace.id] = trace
        return trace

    def upsert_memory(self, trace):
        self.records[trace.id] = trace

    def remove_many(self, record_ids):
        batch = list(record_ids)
        if self.fail_remove_batch:
            raise MemoryStoreError(
                "remove_batch",
                record_count=len(batch),
                cause_type="OSError",
            )
        self.remove_batches.append(batch)
        for record_id in batch:
            self.records.pop(record_id, None)


def _consolidation_controller(response, memory):
    controller = object.__new__(MemoryOperationsController)
    controller.engine = SimpleNamespace(
        memory=memory,
        llm=SimpleNamespace(generate_text=Mock(return_value=(response, {}))),
        operation_ledger=InMemoryOperationLedger(),
    )
    return controller


class LosslessConsolidationTests(unittest.TestCase):
    def setUp(self):
        self.sources = [_trace(f"source-{index}") for index in range(3)]

    def test_empty_or_invalid_insights_never_mutate_sources(self):
        responses = (
            "[]",
            json.dumps([{"conclusion": "", "reasoning": ""}]),
            json.dumps(["not-an-object"]),
            "not-json",
        )
        for response in responses:
            with self.subTest(response=response):
                sources = [_trace(f"source-{index}") for index in range(3)]
                memory = _FakeMemoryManager(sources)
                controller = _consolidation_controller(response, memory)

                controller._dream_consolidation_phase()

                self.assertEqual(memory.added, [])
                self.assertEqual(memory.updated, [])
                memory.store.remove.assert_not_called()
                self.assertTrue(all(not source.is_consolidated_source for source in sources))

    def test_success_writes_all_derived_then_marks_and_retains_sources(self):
        response = json.dumps([
            {
                "tags": ["alpha", "gamma", "beta"],
                "reasoning": "shared pattern",
                "conclusion": "a durable semantic conclusion",
            }
        ])
        memory = _FakeMemoryManager(self.sources)
        controller = _consolidation_controller(response, memory)

        with patch("core.engine.memory_ops.time.time", return_value=5_000.0):
            controller._dream_consolidation_phase()

        self.assertEqual(len(memory.added), 2)
        self.assertEqual(len(memory.updated), 3)
        self.assertEqual(len(memory.add_batches), 1)
        self.assertEqual(len(memory.update_batches), 1)
        memory.store.remove.assert_not_called()
        consolidation_ids = {trace.consolidation_id for trace in memory.added}
        consolidation_ids.update(source.consolidation_id for source in self.sources)
        self.assertEqual(len(consolidation_ids), 1)
        self.assertNotEqual(consolidation_ids, {""})
        self.assertTrue(all(source.is_consolidated_source for source in self.sources))
        self.assertTrue(all(source.consolidated_at == 5_000.0 for source in self.sources))
        self.assertTrue(all(
            trace.consolidation_parent_ids == [source.id for source in self.sources]
            and trace.consolidation_expected_derived_count == 2
            for trace in memory.added
        ))

    def test_completed_batch_is_excluded_when_new_ids_interleave(self):
        completed = [
            _trace(f"z-completed-{index:02d}", created_at=float(index))
            for index in range(15)
        ]
        for source in completed:
            source.is_consolidated_source = True
            source.consolidation_id = "completed-batch"
        fresh = [
            _trace(f"a-new-{index:02d}", created_at=float(index))
            for index in range(3)
        ]
        response = json.dumps([{
            "tags": [],
            "reasoning": "new group only",
            "conclusion": "a stable new conclusion",
        }])
        memory = _FakeMemoryManager(completed + fresh)
        controller = _consolidation_controller(response, memory)

        controller._dream_consolidation_phase()

        self.assertEqual(len(memory.add_batches), 1)
        self.assertEqual(
            set(memory.added[0].consolidation_parent_ids),
            {source.id for source in fresh},
        )
        self.assertEqual(memory.updated, fresh)
        self.assertTrue(all(
            source.consolidation_id == "completed-batch"
            for source in completed
        ))

    def test_incomplete_legacy_manifest_fails_closed_without_llm(self):
        sources = [_trace(f"partial-source-{index}") for index in range(3)]
        parent_ids = [source.id for source in sources]
        consolidation_id = str(__import__("uuid").uuid5(
            __import__("uuid").NAMESPACE_URL,
            "aura:memory-consolidation:" + "|".join(parent_ids),
        ))
        partial = MemoryTrace(
            id=str(__import__("uuid").uuid5(
                __import__("uuid").NAMESPACE_URL,
                f"{consolidation_id}:semantic:0",
            )),
            content="partial derived",
            type=MemoryType.SEMANTIC,
            valence=0.0,
            arousal=0.2,
            importance=1.0,
            consolidation_id=consolidation_id,
            consolidation_parent_ids=parent_ids,
            consolidation_expected_derived_count=2,
        )
        interleaving = _trace("000-interleaving", created_at=1.0)
        memory = _FakeMemoryManager(sources + [partial, interleaving])
        response = json.dumps([{
            "tags": [],
            "reasoning": "resume exact",
            "conclusion": "a completed exact conclusion",
        }])
        controller = _consolidation_controller(response, memory)

        controller._dream_consolidation_phase()

        self.assertEqual(memory.add_batches, [])
        controller.engine.llm.generate_text.assert_not_called()
        self.assertTrue(all(not source.is_consolidated_source for source in sources))
        self.assertFalse(interleaving.is_consolidated_source)

    def test_derived_write_failure_keeps_all_sources_and_propagates(self):
        response = json.dumps([
            {
                "tags": [],
                "reasoning": "shared pattern",
                "conclusion": "a durable semantic conclusion",
            }
        ])
        memory = _FakeMemoryManager(self.sources, fail_add_batch=True)
        controller = _consolidation_controller(response, memory)

        with self.assertRaises(MemoryStoreError):
            controller._dream_consolidation_phase()

        self.assertEqual(len(memory.added), 0)
        self.assertEqual(memory.updated, [])
        memory.store.remove.assert_not_called()
        self.assertTrue(all(not source.is_consolidated_source for source in self.sources))

    def test_source_marker_write_failure_still_retains_sources_and_propagates(self):
        response = json.dumps([
            {
                "tags": [],
                "reasoning": "shared pattern",
                "conclusion": "a durable semantic conclusion",
            }
        ])
        memory = _FakeMemoryManager(self.sources, fail_update_batch=True)
        controller = _consolidation_controller(response, memory)

        with self.assertRaises(MemoryStoreError):
            controller._dream_consolidation_phase()

        self.assertEqual(len(memory.added), 2)
        memory.store.remove.assert_not_called()
        self.assertTrue(all(not source.is_consolidated_source for source in self.sources))

    def test_source_marker_retry_uses_durable_exact_manifest_without_llm(self):
        response = json.dumps([
            {
                "tags": [],
                "reasoning": "shared pattern",
                "conclusion": "a durable semantic conclusion",
            }
        ])
        memory = _FakeMemoryManager(self.sources, fail_update_batch=True)
        controller = _consolidation_controller(response, memory)

        with self.assertRaises(MemoryStoreError):
            controller._dream_consolidation_phase()
        first_ids = [trace.id for trace in memory.added]
        self.assertEqual(len(memory.updated), 0)

        # Simulate a reload and an interleaving source that would otherwise
        # perturb the next selected batch.
        memory.fail_update_batch = False
        new_source = _trace("000-new-source", created_at=1.0)
        memory.records[new_source.id] = new_source
        controller.engine.llm.generate_text.reset_mock()
        controller._dream_consolidation_phase()

        self.assertEqual([trace.id for trace in memory.added], first_ids)
        self.assertEqual(len(set(first_ids)), len(first_ids))
        self.assertTrue(all(source.is_consolidated_source for source in self.sources))
        self.assertFalse(new_source.is_consolidated_source)
        controller.engine.llm.generate_text.assert_not_called()
        self.assertEqual(
            len({source.consolidation_id for source in self.sources}),
            1,
        )
        memory.store.remove.assert_not_called()


class WallClockDecayTests(unittest.TestCase):
    def test_two_decay_phases_at_same_clock_instant_are_idempotent(self):
        trace = _trace(
            "decay-source",
            strength=0.8,
            created_at=1_000.0,
            last_decayed_at=1_000.0,
        )
        memory = SimpleNamespace(
            get_all=Mock(return_value=[trace]),
            update_memory=Mock(),
            remove_many=Mock(),
        )
        skills = SimpleNamespace(decay_skills=Mock())
        ego = SimpleNamespace(stress=0.2, process_trauma_healing=Mock())
        controller = object.__new__(MemoryOperationsController)
        controller.engine = SimpleNamespace(memory=memory, skills=skills, ego=ego)
        controller.apply_semantic_drift = Mock(return_value=False)

        with patch("core.engine.memory_ops.time.time", return_value=87_400.0):
            controller._decay_phase()
            strength_after_first = trace.strength
            controller._decay_phase()

        self.assertEqual(trace.last_decayed_at, 87_400.0)
        self.assertEqual(trace.strength, strength_after_first)
        self.assertEqual(memory.update_memory.call_count, 1)
        skills.decay_skills.assert_called_once_with(days_passed=1.0)
        self.assertEqual(ego.process_trauma_healing.call_count, 1)
        self.assertEqual(controller.apply_semantic_drift.call_count, 1)

    def test_consolidated_source_is_not_pruned(self):
        trace = _trace(
            "retained-source",
            strength=0.01,
            created_at=0.0,
            last_decayed_at=1_000.0,
        )
        trace.is_consolidated_source = True
        memory = SimpleNamespace(
            get_all=Mock(return_value=[trace]),
            update_memory=Mock(),
            remove_many=Mock(),
        )
        controller = object.__new__(MemoryOperationsController)
        controller.engine = SimpleNamespace(
            memory=memory,
            skills=SimpleNamespace(decay_skills=Mock()),
            ego=SimpleNamespace(stress=0.0, process_trauma_healing=Mock()),
        )
        controller.apply_semantic_drift = Mock(return_value=False)

        with patch("core.engine.memory_ops.time.time", return_value=87_400.0):
            controller._decay_phase()

        memory.remove_many.assert_not_called()


class ReappraisalPersistenceTests(unittest.TestCase):
    def _controller(self, trace, *, upsert_side_effect=None):
        memory = SimpleNamespace(
            get_all=Mock(return_value=[trace]),
            add_memory=Mock(),
            update_memory=Mock(),
            upsert_memory=Mock(side_effect=upsert_side_effect),
        )
        controller = object.__new__(MemoryOperationsController)
        controller.engine = SimpleNamespace(
            memory=memory,
            ego=SimpleNamespace(
                get_active_beliefs=Mock(return_value=[]),
            ),
            llm=SimpleNamespace(generate_text=Mock(return_value=(
                json.dumps({
                    "action": "REJECT",
                    "reasoning": "stable",
                    "new_belief": "",
                }),
                {},
            ))),
            operation_ledger=InMemoryOperationLedger(),
        )
        return controller, memory

    def test_content_tag_cleanup_uses_vector_upsert(self):
        trace = _trace("reappraisal")
        trace.content = "[ToReevaluate] private contradiction"
        controller, memory = self._controller(trace)

        with patch("builtins.print"):
            controller._cognitive_reappraisal_phase()

        self.assertEqual(trace.content, "private contradiction")
        memory.upsert_memory.assert_called_once_with(trace)
        memory.update_memory.assert_called_once_with(trace)

    def test_cleanup_store_failure_is_visible_safe_and_rolls_back(self):
        trace = _trace("reappraisal-failure")
        trace.content = "[ToReevaluate] private contradiction"
        failure = MemoryStoreError("upsert", cause_type="OSError")
        controller, _memory = self._controller(
            trace,
            upsert_side_effect=failure,
        )
        safe_logger = Mock()

        with patch("builtins.print"), patch(
            "core.logger.get_logger", return_value=safe_logger
        ):
            with self.assertRaises(MemoryStoreError):
                controller._cognitive_reappraisal_phase()

        self.assertEqual(
            trace.content,
            "[ToReevaluate] private contradiction",
        )
        log_args = safe_logger.error.call_args.args
        rendered = str(log_args[0]) % tuple(log_args[1:])
        self.assertNotIn("private contradiction", rendered)

    def test_analysis_failure_retains_retry_marker_and_logs_no_message(self):
        trace = _trace("analysis-failure")
        trace.content = "[ToReevaluate] private contradiction"
        controller, memory = self._controller(trace)
        controller.engine.llm.generate_text.side_effect = RuntimeError(
            "private contradiction service message"
        )
        safe_logger = Mock()

        with patch("builtins.print"), patch(
            "core.logger.get_logger", return_value=safe_logger
        ):
            controller._cognitive_reappraisal_phase()

        self.assertEqual(trace.content, "private contradiction")
        self.assertEqual(len(trace.overlays), 1)
        self.assertTrue(trace.overlays[0].startswith("[ToReevaluate:"))
        memory.upsert_memory.assert_called_once_with(trace)
        memory.update_memory.assert_not_called()
        log_args = safe_logger.warning.call_args.args
        rendered = str(log_args[0]) % tuple(log_args[1:])
        self.assertNotIn("private contradiction", rendered)

    def test_evolve_retry_uses_same_derived_identifier(self):
        trace = _trace("evolve-source")
        trace.content = "[ToReevaluate] contradiction"
        failure = MemoryStoreError("upsert", cause_type="OSError")
        records = [trace]

        def persist_child(child):
            records.append(child)

        memory = SimpleNamespace(
            get_all=Mock(side_effect=lambda: list(records)),
            add_memory=Mock(side_effect=persist_child),
            update_memory=Mock(side_effect=[failure, None]),
            upsert_memory=Mock(),
        )
        first_response = json.dumps({
            "action": "EVOLVE",
            "reasoning": "stable",
            "new_belief": "first refined belief",
        })
        controller = object.__new__(MemoryOperationsController)
        controller.engine = SimpleNamespace(
            memory=memory,
            ego=SimpleNamespace(get_active_beliefs=Mock(return_value=[])),
            llm=SimpleNamespace(generate_text=Mock(return_value=(
                first_response,
                {},
            ))),
            operation_ledger=InMemoryOperationLedger(),
        )

        with patch("builtins.print"):
            with self.assertRaises(MemoryStoreError):
                controller._cognitive_reappraisal_phase()
            controller._cognitive_reappraisal_phase()

        derived_ids = [call.args[0].id for call in memory.add_memory.call_args_list]
        self.assertEqual(len(derived_ids), 1)
        controller.engine.llm.generate_text.assert_called_once()
        self.assertEqual(trace.content, "contradiction")


class IdentityAndBeliefPersistenceTests(unittest.TestCase):
    def test_identity_memory_store_failure_is_rethrown_with_safe_log(self):
        failure = MemoryStoreError("add", cause_type="OSError")
        controller = object.__new__(MemoryOperationsController)
        ego = SimpleNamespace(
            lock=threading.RLock(),
            evolved_insight="",
            actionable_lessons=[],
        )
        controller.engine = SimpleNamespace(
            stm_lock=threading.RLock(),
            short_term_buffer=["one", "two", "three", "four"],
            ego=ego,
            memory=SimpleNamespace(add_memory=Mock(side_effect=failure)),
            value_system=SimpleNamespace(get_moral_context=Mock(return_value="")),
            llm=SimpleNamespace(generate_text=Mock(return_value=(
                json.dumps({
                    "insight": "a sufficiently durable identity insight",
                    "actionable_lessons": [],
                    "value_updates": [],
                }),
                {},
            ))),
        )
        safe_logger = Mock()

        with patch("builtins.print"), patch(
            "core.logger.get_logger", return_value=safe_logger
        ):
            with self.assertRaises(MemoryStoreError):
                controller._identity_evolution_phase()

        log_args = safe_logger.error.call_args.args
        rendered = str(log_args[0]) % tuple(log_args[1:])
        self.assertNotIn("identity insight", rendered)
        self.assertEqual(ego.evolved_insight, "")
        self.assertEqual(ego.actionable_lessons, [])

    def test_identity_validates_entire_payload_before_memory_write(self):
        memory = SimpleNamespace(add_memory=Mock())
        ego = SimpleNamespace(
            lock=threading.RLock(),
            evolved_insight="old",
            actionable_lessons=["old lesson"],
        )
        controller = object.__new__(MemoryOperationsController)
        controller.engine = SimpleNamespace(
            stm_lock=threading.RLock(),
            short_term_buffer=["one", "two", "three", "four"],
            ego=ego,
            memory=memory,
            value_system=SimpleNamespace(get_moral_context=Mock(return_value="")),
            llm=SimpleNamespace(generate_text=Mock(return_value=(
                json.dumps({
                    "insight": "a valid-looking durable insight",
                    "actionable_lessons": 1,
                    "value_updates": [],
                }),
                {},
            ))),
        )

        with patch("builtins.print"):
            controller._identity_evolution_phase()

        memory.add_memory.assert_not_called()
        self.assertEqual(ego.evolved_insight, "old")
        self.assertEqual(ego.actionable_lessons, ["old lesson"])

    def test_belief_merge_retry_deletes_exact_parents_without_second_llm(self):
        beliefs = [
            MemoryTrace(
                id=f"belief-{index}",
                content=f"Belief {index}",
                type=MemoryType.CORE,
                valence=0.0,
                arousal=0.2,
                importance=1.0,
                created_at=float(index),
            )
            for index in range(2)
        ]
        memory = _FakeMemoryManager(beliefs, fail_remove_batch=True)
        response = json.dumps({
            "analysis": "conflict",
            "resolutions": [{
                "type": "MERGE",
                "indices": [1, 0],
                "new_content": "a mature belief",
            }],
        })
        controller = object.__new__(MemoryOperationsController)
        controller.engine = SimpleNamespace(
            memory=memory,
            llm=SimpleNamespace(generate_text=Mock(return_value=(response, {}))),
        )

        with patch("builtins.print"), patch("os.makedirs"), patch(
            "core.engine.memory_ops.open", mock_open(), create=True
        ):
            with self.assertRaises(MemoryStoreError):
                controller._belief_evolution_phase()
            derived_ids = [
                trace.id for trace in memory.added
                if trace.consolidation_id.startswith("belief-merge:")
            ]
            self.assertEqual(len(derived_ids), 1)

            memory.fail_remove_batch = False
            controller.engine.llm.generate_text.reset_mock()
            controller._belief_evolution_phase()

        expected_id = _belief_merge_child_id(
            ["belief-0", "belief-1"],
            "a mature belief",
        )
        self.assertEqual(derived_ids, [expected_id])
        self.assertEqual(len(memory.add_batches), 1)
        self.assertEqual(len(memory.add_batches[0]), 2)
        self.assertEqual(memory.remove_batches, [["belief-0", "belief-1"]])
        controller.engine.llm.generate_text.assert_not_called()

    def test_pure_delete_intent_survives_failure_and_retries_without_llm(self):
        beliefs = [
            MemoryTrace(
                id=f"delete-belief-{index}",
                content=f"Belief delete {index}",
                type=MemoryType.CORE,
                valence=0.0,
                arousal=0.2,
                importance=1.0,
                created_at=float(index),
            )
            for index in range(2)
        ]
        memory = _FakeMemoryManager(beliefs, fail_remove_batch=True)
        response = json.dumps({
            "analysis": "duplicate",
            "resolutions": [{"type": "DELETE", "indices": [0]}],
        })
        controller = object.__new__(MemoryOperationsController)
        controller.engine = SimpleNamespace(
            memory=memory,
            llm=SimpleNamespace(generate_text=Mock(return_value=(response, {}))),
        )

        with patch("builtins.print"), patch("os.makedirs"), patch(
            "core.engine.memory_ops.open", mock_open(), create=True
        ):
            with self.assertRaises(MemoryStoreError):
                controller._belief_evolution_phase()
            self.assertEqual(len(memory.added), 1)
            self.assertTrue(memory.added[0].consolidation_id.startswith(
                "belief-delete:"
            ))
            memory.fail_remove_batch = False
            controller.engine.llm.generate_text.reset_mock()
            controller._belief_evolution_phase()

        self.assertEqual(memory.remove_batches, [["delete-belief-0"]])
        controller.engine.llm.generate_text.assert_not_called()

    def test_mixed_merge_delete_intent_retries_all_parents(self):
        beliefs = [
            MemoryTrace(
                id=f"mixed-belief-{index}",
                content=f"Belief mixed {index}",
                type=MemoryType.CORE,
                valence=0.0,
                arousal=0.2,
                importance=1.0,
                created_at=float(index),
            )
            for index in range(4)
        ]
        memory = _FakeMemoryManager(beliefs, fail_remove_batch=True)
        response = json.dumps({
            "analysis": "mixed",
            "resolutions": [
                {
                    "type": "MERGE",
                    "indices": [0, 1],
                    "new_content": "merged",
                },
                {"type": "DELETE", "indices": [2]},
            ],
        })
        controller = object.__new__(MemoryOperationsController)
        controller.engine = SimpleNamespace(
            memory=memory,
            llm=SimpleNamespace(generate_text=Mock(return_value=(response, {}))),
        )

        with patch("builtins.print"), patch("os.makedirs"), patch(
            "core.engine.memory_ops.open", mock_open(), create=True
        ):
            with self.assertRaises(MemoryStoreError):
                controller._belief_evolution_phase()
            memory.fail_remove_batch = False
            controller.engine.llm.generate_text.reset_mock()
            controller._belief_evolution_phase()

        self.assertEqual(
            memory.remove_batches,
            [["mixed-belief-0", "mixed-belief-1", "mixed-belief-2"]],
        )
        controller.engine.llm.generate_text.assert_not_called()


class WallClockMigrationTests(unittest.TestCase):
    def test_legacy_checkpoint_is_persisted_immediately_and_only_once(self):
        store = object.__new__(VectorStore)
        metadata = store._obj_to_dict(_trace("legacy"))
        metadata.pop("last_decayed_at")
        with patch("components.vector_store.time.time", return_value=2_000.0):
            trace = store._dict_to_obj(metadata)
        memory = SimpleNamespace(
            get_all=Mock(return_value=[trace]),
            update_memory=Mock(),
            remove_many=Mock(),
        )
        controller = object.__new__(MemoryOperationsController)
        controller.engine = SimpleNamespace(
            memory=memory,
            skills=SimpleNamespace(decay_skills=Mock()),
            ego=SimpleNamespace(stress=0.0, process_trauma_healing=Mock()),
        )
        controller.apply_semantic_drift = Mock(return_value=False)

        with patch("core.engine.memory_ops.time.time", return_value=2_000.0):
            controller._decay_phase()
            controller._decay_phase()

        memory.update_memory.assert_called_once_with(trace)
        self.assertFalse(hasattr(trace, "_last_decay_checkpoint_pending"))
        controller.apply_semantic_drift.assert_not_called()

    def test_legacy_checkpoint_write_failure_retries_without_losing_marker(self):
        trace = _trace("legacy-retry", last_decayed_at=2_000.0)
        trace._last_decay_checkpoint_pending = True
        failure = MemoryStoreError("update_meta", cause_type="OSError")
        memory = SimpleNamespace(
            get_all=Mock(return_value=[trace]),
            update_memory=Mock(side_effect=[failure, None]),
            remove_many=Mock(),
        )
        controller = object.__new__(MemoryOperationsController)
        controller.engine = SimpleNamespace(
            memory=memory,
            skills=SimpleNamespace(decay_skills=Mock()),
            ego=SimpleNamespace(stress=0.0, process_trauma_healing=Mock()),
        )
        controller.apply_semantic_drift = Mock(return_value=False)

        with patch("core.engine.memory_ops.time.time", return_value=2_000.0):
            with self.assertRaises(MemoryStoreError):
                controller._decay_phase()
            self.assertTrue(trace._last_decay_checkpoint_pending)
            controller._decay_phase()

        self.assertFalse(hasattr(trace, "_last_decay_checkpoint_pending"))
        self.assertEqual(memory.update_memory.call_count, 2)

    def test_subsecond_elapsed_does_not_run_healing_or_drift(self):
        trace = _trace("epsilon", last_decayed_at=1_000.0)
        memory = SimpleNamespace(
            get_all=Mock(return_value=[trace]),
            update_memory=Mock(),
            remove_many=Mock(),
        )
        healing = Mock()
        controller = object.__new__(MemoryOperationsController)
        controller.engine = SimpleNamespace(
            memory=memory,
            skills=SimpleNamespace(decay_skills=Mock()),
            ego=SimpleNamespace(stress=0.0, process_trauma_healing=healing),
        )
        controller.apply_semantic_drift = Mock(return_value=False)

        with patch("core.engine.memory_ops.time.time", return_value=1_000.5):
            controller._decay_phase()

        memory.update_memory.assert_not_called()
        healing.assert_not_called()
        controller.apply_semantic_drift.assert_not_called()

    def test_one_second_healing_effect_is_scaled_by_elapsed_days(self):
        trace = _trace("scaled-healing", last_decayed_at=1_000.0)
        memory = SimpleNamespace(
            get_all=Mock(return_value=[trace]),
            update_memory=Mock(),
            remove_many=Mock(),
        )
        ego = SimpleNamespace(stress=0.0, resilience=0.2)

        def fixed_healing(memory_trace):
            memory_trace.valence += 0.5
            ego.resilience += 0.5

        ego.process_trauma_healing = Mock(side_effect=fixed_healing)
        controller = object.__new__(MemoryOperationsController)
        controller.engine = SimpleNamespace(
            memory=memory,
            skills=SimpleNamespace(decay_skills=Mock()),
            ego=ego,
        )
        controller.apply_semantic_drift = Mock(return_value=False)

        with patch("core.engine.memory_ops.time.time", return_value=1_001.0):
            controller._decay_phase()

        self.assertAlmostEqual(trace.valence, 0.5 / 86_400.0)
        self.assertAlmostEqual(ego.resilience, 0.2 + 0.5 / 86_400.0)
        controller.apply_semantic_drift.assert_called_once_with(
            trace,
            elapsed_days=1.0 / 86_400.0,
        )

    def test_semantic_drift_probability_is_scaled_by_elapsed_days(self):
        trace = _trace("scaled-drift")
        trace.recall_count = 2
        llm = SimpleNamespace(generate_text=Mock(return_value=("replacement", {})))
        controller = object.__new__(MemoryOperationsController)
        controller.engine = SimpleNamespace(
            llm=llm,
            memory=SimpleNamespace(upsert_memory=Mock()),
        )

        with patch("core.engine.memory_ops.random.random", return_value=0.001):
            changed = controller.apply_semantic_drift(
                trace,
                elapsed_days=1.0 / 86_400.0,
            )

        self.assertFalse(changed)
        llm.generate_text.assert_not_called()

    def test_decay_write_failure_rolls_back_in_memory_state(self):
        trace = _trace("rollback", strength=0.8, last_decayed_at=1_000.0)
        original = copy.deepcopy(trace.__dict__)
        failure = MemoryStoreError("update_meta", cause_type="OSError")
        memory = SimpleNamespace(
            get_all=Mock(return_value=[trace]),
            update_memory=Mock(side_effect=failure),
            remove_many=Mock(),
        )

        def mutate_during_healing(memory_trace):
            memory_trace.valence = 0.9
            controller.engine.ego.resilience = 0.9

        controller = object.__new__(MemoryOperationsController)
        controller.engine = SimpleNamespace(
            memory=memory,
            skills=SimpleNamespace(decay_skills=Mock()),
            ego=SimpleNamespace(
                stress=0.0,
                resilience=0.3,
                process_trauma_healing=Mock(side_effect=mutate_during_healing),
            ),
        )
        controller.apply_semantic_drift = Mock(return_value=False)

        with patch("core.engine.memory_ops.time.time", return_value=87_400.0):
            with self.assertRaises(MemoryStoreError):
                controller._decay_phase()

        self.assertEqual(trace.__dict__, original)
        self.assertEqual(controller.engine.ego.resilience, 0.3)

    def test_pending_manifest_parent_is_not_pruned_before_marker_retry(self):
        source = _trace("pending-parent", strength=0.01)
        derived = MemoryTrace(
            id="derived",
            content="derived",
            type=MemoryType.SEMANTIC,
            valence=0.0,
            arousal=0.2,
            importance=1.0,
            consolidation_id="pending",
            consolidation_parent_ids=[source.id],
            consolidation_expected_derived_count=1,
            last_decayed_at=1_000.0,
        )
        memory = SimpleNamespace(
            get_all=Mock(return_value=[source, derived]),
            update_memory=Mock(),
            remove_many=Mock(),
        )
        controller = object.__new__(MemoryOperationsController)
        controller.engine = SimpleNamespace(
            memory=memory,
            skills=SimpleNamespace(decay_skills=Mock()),
            ego=SimpleNamespace(stress=0.0, process_trauma_healing=Mock()),
        )
        controller.apply_semantic_drift = Mock(return_value=False)

        with patch("core.engine.memory_ops.time.time", return_value=87_400.0):
            controller._decay_phase()

        memory.remove_many.assert_not_called()


if __name__ == "__main__":
    unittest.main()
