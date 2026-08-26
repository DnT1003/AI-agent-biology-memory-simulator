import ast
import json
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

from components.chroma_rest_client import CollectionWrapper
from components.vector_store import MemoryReadError, MemorySchemaError, VectorStore
from core.memory import MemoryManager, MemoryTrace, MemoryType
from core.memory_context import (
    MemoryAccessContext,
    MemoryAccessError,
    MemoryScope,
    maintenance_memory_context,
    memory_context_scope,
)


def _trace(record_id="record", *, scope="owner", privacy="standard"):
    return MemoryTrace(
        id=record_id,
        content=f"memory-{record_id}",
        type=MemoryType.EPISODIC,
        valence=0.1,
        arousal=0.2,
        importance=0.5,
        created_at=1_000.0,
        last_recalled=1_001.0,
        last_decayed_at=1_002.0,
        scope=scope,
        privacy=privacy,
    )


def _manager(store, *, vector=None):
    manager = object.__new__(MemoryManager)
    manager.lock = threading.RLock()
    manager.embedder = SimpleNamespace(
        encode=Mock(return_value=[0.25] if vector is None else vector)
    )
    manager.store = store
    manager._access_migration_complete = False
    return manager


def _assert_access_where(test_case, where, scopes):
    rendered = json.dumps(where, sort_keys=True)
    test_case.assertIn('"scope"', rendered)
    test_case.assertIn('"privacy"', rendered)
    test_case.assertIn('"standard"', rendered)
    for scope in scopes:
        test_case.assertIn(f'"{scope}"', rendered)


class ProductionMemoryBoundaryTests(unittest.TestCase):
    def test_core_never_calls_unscoped_vector_store_mutations(self):
        forbidden = {
            "add",
            "add_batch",
            "upsert",
            "update_meta",
            "update_meta_batch",
            "update_vector",
            "remove",
            "remove_batch",
            "clear_all",
            "reset_collection",
        }
        core_root = Path(__file__).resolve().parents[1] / "core"
        violations = []
        for source_path in sorted(core_root.rglob("*.py")):
            tree = ast.parse(
                source_path.read_text(encoding="utf-8-sig"),
                filename=str(source_path),
            )
            for node in ast.walk(tree):
                function = node.func if isinstance(node, ast.Call) else None
                owner = function.value if isinstance(function, ast.Attribute) else None
                if (
                    isinstance(owner, ast.Attribute)
                    and owner.attr == "store"
                    and function.attr in forbidden
                ):
                    violations.append(
                        f"{source_path.relative_to(core_root)}:{node.lineno}:"
                        f"{function.attr}"
                    )
        self.assertEqual(violations, [])


class MemoryManagerAccessTests(unittest.TestCase):
    def test_private_ephemeral_denies_every_api_before_embedder_or_store(self):
        store = Mock(spec=[])
        manager = _manager(store)
        trace = _trace()
        operations = (
            lambda: manager.add_memory(trace),
            lambda: manager.add_memories([trace]),
            lambda: manager.update_memory(trace),
            lambda: manager.update_memories([trace]),
            lambda: manager.upsert_memory(trace),
            lambda: manager.search_memories("secret"),
            lambda: manager.chronological_recall(0, 2_000),
            manager.get_all,
            lambda: manager.remove(trace.id),
            lambda: manager.remove_many([trace.id]),
            manager.enforce_garbage_collection,
        )
        context = MemoryAccessContext(
            read_scopes=(MemoryScope.OWNER,),
            write_scope=MemoryScope.OWNER,
            private_ephemeral=True,
        )

        with memory_context_scope(context):
            for operation in operations:
                with self.subTest(operation=operation), self.assertRaises(
                    MemoryAccessError
                ):
                    operation()

        manager.embedder.encode.assert_not_called()
        self.assertEqual(store.mock_calls, [])

    def test_empty_read_scope_denies_but_local_only_does_not(self):
        denied_store = Mock(spec=[])
        denied = _manager(denied_store)
        with memory_context_scope(
            MemoryAccessContext(read_scopes=(), write_scope=None)
        ), self.assertRaises(MemoryAccessError):
            denied.search_memories("not embedded")
        denied.embedder.encode.assert_not_called()
        self.assertEqual(denied_store.mock_calls, [])

        migrate = Mock(return_value=0)
        get_all = Mock(return_value=[])
        local = _manager(SimpleNamespace(
            supports_memory_access_policy=True,
            migrate_legacy_metadata=migrate,
            get_all_metadata=get_all,
        ))
        with memory_context_scope(MemoryAccessContext(local_only=True)):
            self.assertEqual(local.get_all(), [])
        migrate.assert_called_once_with()
        get_all.assert_called_once_with(read_scopes=("agent", "owner"))

    def test_local_only_blocks_network_embedder_before_content_or_query_leaves(self):
        store = Mock(spec=[])
        manager = _manager(store)
        trace = _trace("local-secret")
        original_provenance = (
            trace.origin_kind,
            trace.origin_source,
            trace.source_event_id,
        )
        context = MemoryAccessContext(local_only=True)

        with memory_context_scope(context):
            for operation in (
                lambda: manager.add_memory(trace),
                lambda: manager.add_memories([trace]),
                lambda: manager.upsert_memory(trace),
                lambda: manager.search_memories("local secret query"),
            ):
                with self.subTest(operation=operation), self.assertRaises(
                    MemoryAccessError
                ) as raised:
                    operation()
                self.assertEqual(
                    raised.exception.reason,
                    "local_embedding_unavailable",
                )

        manager.embedder.encode.assert_not_called()
        self.assertEqual(store.mock_calls, [])
        self.assertEqual(
            (
                trace.origin_kind,
                trace.origin_source,
                trace.source_event_id,
            ),
            original_provenance,
        )

    def test_new_add_stamps_context_but_update_never_restamps_provenance(self):
        store = SimpleNamespace(
            supports_memory_access_policy=True,
            migrate_legacy_metadata=Mock(return_value=0),
            add_scoped=Mock(side_effect=lambda _id, _vector, value, **_kw: value),
            update_meta_scoped=Mock(
                side_effect=lambda _id, value, **_kw: value
            ),
        )
        manager = _manager(store)
        trace = _trace()
        trace.provenance_parent_ids = ["parent"]
        first = MemoryAccessContext(
            origin_kind="interaction",
            origin_source="discord",
            source_event_id="event-1",
        )
        with memory_context_scope(first):
            manager.add_memory(trace)

        self.assertEqual(trace.origin_kind, "interaction")
        self.assertEqual(trace.origin_source, "discord")
        self.assertEqual(trace.source_event_id, "event-1")
        self.assertEqual(trace.provenance_parent_ids, ["parent"])

        second = MemoryAccessContext(
            origin_kind="maintenance",
            origin_source="nightly",
            source_event_id="event-2",
        )
        with memory_context_scope(second):
            manager.update_memory(trace)
        self.assertEqual(
            (trace.origin_kind, trace.origin_source, trace.source_event_id),
            ("interaction", "discord", "event-1"),
        )

    def test_owner_context_cannot_mutate_agent_and_writable_search_is_owner_only(self):
        store = SimpleNamespace(
            migrate_legacy_metadata=Mock(return_value=0),
            update_meta=Mock(),
            search=Mock(return_value=[]),
        )
        manager = _manager(store)
        with self.assertRaises(MemoryAccessError):
            manager.update_memory(_trace("agent", scope="agent"))
        store.update_meta.assert_not_called()

        with self.assertRaises(MemoryAccessError) as unsupported:
            manager.search_memories("candidate", writable_only=True)
        self.assertEqual(unsupported.exception.reason, "unsupported_store")
        store.search.assert_not_called()
        manager.embedder.encode.assert_not_called()

        policy_store = SimpleNamespace(
            supports_memory_access_policy=True,
            migrate_legacy_metadata=Mock(return_value=0),
            search=Mock(return_value=[]),
        )
        policy_manager = _manager(policy_store)
        policy_manager.search_memories("candidate", writable_only=True)
        self.assertEqual(
            policy_store.search.call_args.kwargs["read_scopes"],
            ("owner",),
        )

    def test_maintenance_can_update_existing_scopes_but_cannot_generic_create(self):
        store = SimpleNamespace(
            supports_memory_access_policy=True,
            migrate_legacy_metadata=Mock(return_value=0),
            add_scoped=Mock(),
            update_meta_scoped=Mock(
                side_effect=lambda _id, value, **_kw: value
            ),
        )
        manager = _manager(store)
        context = maintenance_memory_context(origin_kind="decay")
        agent_trace = _trace("agent", scope="agent")
        with memory_context_scope(context):
            manager.update_memory(agent_trace)
            with self.assertRaises(MemoryAccessError):
                manager.add_memory(agent_trace)

        store.update_meta_scoped.assert_called_once_with(
            "agent",
            agent_trace,
            allowed_scopes=("agent", "owner"),
        )
        store.add_scoped.assert_not_called()
        manager.embedder.encode.assert_not_called()

    def test_legacy_upgrade_accepts_current_sleep_event_without_rewriting_it(self):
        trace = _trace("legacy-derived")
        trace.consolidation_parent_ids = ["p1", "p2", "p3"]
        trace.origin_kind = "legacy"
        trace.origin_source = "schema_v5"
        upgraded = _trace("legacy-derived")
        upgraded.origin_kind = "consolidation"
        upgraded.origin_source = "sleep"
        upgraded.provenance_parent_ids = ["p1", "p2", "p3"]
        policy_store = SimpleNamespace(
            supports_memory_access_policy=True,
            migrate_legacy_metadata=Mock(return_value=0),
            upgrade_legacy_provenance_scoped=Mock(return_value=upgraded),
        )
        manager = _manager(policy_store)
        context = MemoryAccessContext(
            origin_kind="consolidation",
            origin_source="sleep",
            source_event_id="current-sleep-event",
        )

        with memory_context_scope(context):
            manager.upgrade_legacy_provenance(trace)

        self.assertIsNone(trace.source_event_id)
        self.assertEqual(trace.provenance_parent_ids, ["p1", "p2", "p3"])
        policy_store.upgrade_legacy_provenance_scoped.assert_called_once()

    def test_migration_runs_once_under_manager_and_corruption_aborts_query(self):
        fake = SimpleNamespace(
            supports_memory_access_policy=True,
            migrate_legacy_metadata=Mock(return_value=1),
            get_all_metadata=Mock(return_value=[]),
        )
        manager = _manager(fake)
        manager.get_all()
        manager.get_all()
        fake.migrate_legacy_metadata.assert_called_once_with()
        self.assertEqual(fake.get_all_metadata.call_count, 2)

        store = object.__new__(VectorStore)
        collection = Mock()
        collection.get.return_value = {
            "ids": ["corrupt"],
            "metadatas": [{"schema_version": "99", "private": "payload"}],
        }
        store.collection = collection
        corrupt_manager = _manager(store)
        with self.assertRaises(MemorySchemaError):
            corrupt_manager.search_memories("must-not-embed")
        corrupt_manager.embedder.encode.assert_not_called()
        collection.update.assert_not_called()
        collection.query.assert_not_called()
        collection.count.assert_not_called()
        self.assertFalse(corrupt_manager._access_migration_complete)


class VectorStoreAccessTests(unittest.TestCase):
    def setUp(self):
        self.store = object.__new__(VectorStore)
        self.store.collection = Mock()

    def test_v1_v5_lazy_migration_assigns_explicit_quarantine_policy(self):
        legacy_v4 = {
            "schema_version": "4",
            "content": "old unknown memory",
            "type": "episodic",
            "valence": 0.0,
            "arousal": 0.2,
            "importance": 0.5,
            "id": "legacy-v4",
            "created_at": 100.0,
            "last_recalled": 101.0,
        }
        legacy_v5 = dict(legacy_v4, schema_version="5", id="legacy-v5")
        self.store.collection.get.return_value = {
            "ids": ["legacy-v4", "legacy-v5"],
            "metadatas": [legacy_v4, legacy_v5],
        }

        self.assertEqual(self.store.migrate_legacy_metadata(), 2)

        kwargs = self.store.collection.update.call_args.kwargs
        self.assertEqual(kwargs["ids"], ["legacy-v4", "legacy-v5"])
        migrated = kwargs["metadatas"]
        self.assertEqual(migrated[0]["schema_version"], "6")
        self.assertEqual(migrated[0]["scope"], "owner")
        self.assertEqual(migrated[0]["privacy"], "legacy_unknown")
        self.assertEqual(migrated[1]["privacy"], "standard")

    def test_scoped_reads_always_push_scope_and_privacy_into_chroma_where(self):
        self.store.collection.get.return_value = {"metadatas": []}
        self.store.get_all_metadata(read_scopes=("owner",), min_strength=0.2)
        all_where = self.store.collection.get.call_args.kwargs["where"]
        _assert_access_where(self, all_where, ("owner",))
        self.assertIn('"strength"', json.dumps(all_where))

        self.store.get_by_time_range(0, 2_000, read_scopes=("owner",))
        time_where = self.store.collection.get.call_args.kwargs["where"]
        _assert_access_where(self, time_where, ("owner",))
        self.assertIn('"timestamp"', json.dumps(time_where))

        self.store.collection.count.return_value = 1
        self.store.collection.query.return_value = {
            "ids": [[]],
            "distances": [[]],
            "metadatas": [[]],
        }
        self.store.search([0.1], read_scopes=("owner",), min_strength=0.2)
        search_where = self.store.collection.query.call_args.kwargs["where"]
        _assert_access_where(self, search_where, ("owner",))
        self.assertIn('"strength"', json.dumps(search_where))

    def test_duplicate_add_is_noop_only_for_exact_identity(self):
        existing = _trace("same")
        existing.origin_kind = "interaction"
        existing.origin_source = "discord"
        existing.source_event_id = "original-event"
        existing.provenance_parent_ids = ["original-parent"]
        self.store.collection.get.return_value = {
            "ids": ["same"],
            "metadatas": [self.store._obj_to_dict(existing)],
        }

        exact_retry = _trace("same")
        exact_retry.origin_kind = "interaction"
        exact_retry.origin_source = "discord"
        exact_retry.source_event_id = "original-event"
        exact_retry.provenance_parent_ids = ["original-parent"]
        persisted = self.store.add_scoped(
            "same",
            [0.2],
            exact_retry,
            allowed_scopes=("owner",),
        )
        self.assertEqual(
            (
                persisted.origin_kind,
                persisted.origin_source,
                persisted.source_event_id,
                persisted.provenance_parent_ids,
            ),
            (
                "interaction",
                "discord",
                "original-event",
                ["original-parent"],
            ),
        )
        self.store.collection.add.assert_not_called()
        self.store.collection.upsert.assert_not_called()

        forged = _trace("same")
        forged.origin_kind = "maintenance"
        forged.origin_source = "nightly"
        forged.provenance_parent_ids = ["replacement-parent"]
        with self.assertRaises(MemoryAccessError) as mismatch:
            self.store.add_scoped(
                "same",
                [9.9],
                forged,
                allowed_scopes=("owner",),
            )
        self.assertEqual(mismatch.exception.reason, "create_collision_mismatch")
        self.store.collection.add.assert_not_called()
        self.store.collection.upsert.assert_not_called()

    def test_scoped_create_uses_add_and_recovers_only_an_exact_race(self):
        fresh = _trace("fresh")
        self.store.collection.get.side_effect = [
            {"ids": [], "metadatas": []},
            {
                "ids": ["fresh"],
                "metadatas": [self.store._obj_to_dict(fresh)],
                "embeddings": np.asarray([[0.2]], dtype=np.float32),
            },
        ]
        persisted = self.store.add_scoped(
            "fresh",
            [0.2],
            fresh,
            allowed_scopes=("owner",),
        )
        self.assertEqual(persisted.id, "fresh")
        self.store.collection.add.assert_called_once()
        self.store.collection.upsert.assert_not_called()

        raced = _trace("raced")
        retry = _trace("raced")
        self.store.collection.reset_mock()
        self.store.collection.add.side_effect = RuntimeError("duplicate")
        self.store.collection.get.side_effect = [
            {"ids": [], "metadatas": []},
            {
                "ids": ["raced"],
                "metadatas": [self.store._obj_to_dict(raced)],
                "embeddings": [[0.7]],
            },
        ]
        canonical = self.store.add_scoped(
            "raced",
            [0.7],
            retry,
            allowed_scopes=("owner",),
        )
        self.assertEqual(canonical.id, "raced")
        self.assertIsNone(canonical.source_event_id)
        self.store.collection.upsert.assert_not_called()

    def test_create_identity_includes_expected_derived_count(self):
        existing = _trace("derived")
        existing.consolidation_id = "consolidation-1"
        existing.consolidation_expected_derived_count = 1
        incoming = _trace("derived")
        incoming.consolidation_id = "consolidation-1"
        incoming.consolidation_expected_derived_count = 2
        self.store.collection.get.return_value = {
            "ids": ["derived"],
            "metadatas": [self.store._obj_to_dict(existing)],
        }

        with self.assertRaises(MemoryAccessError):
            self.store.add_scoped(
                "derived",
                [0.2],
                incoming,
                allowed_scopes=("owner",),
            )
        self.store.collection.add.assert_not_called()

    def test_owner_cannot_update_or_delete_existing_agent_record(self):
        agent = _trace("agent", scope="agent")
        self.store.collection.get.return_value = {
            "ids": ["agent"],
            "metadatas": [self.store._obj_to_dict(agent)],
        }
        owner_shape = _trace("agent", scope="owner")

        with self.assertRaises(MemoryAccessError):
            self.store.update_meta_scoped(
                "agent",
                owner_shape,
                allowed_scopes=("owner",),
            )
        with self.assertRaises(MemoryAccessError):
            self.store.remove_scoped("agent", allowed_scopes=("owner",))
        self.store.collection.update.assert_not_called()
        self.store.collection.delete.assert_not_called()

    def test_legacy_provenance_upgrade_is_one_way_and_rejects_forgery(self):
        existing = _trace("derived")
        existing.consolidation_id = "batch-1"
        existing.consolidation_parent_ids = ["p1", "p2", "p3"]
        existing.origin_kind = "unknown"
        existing.origin_source = "unknown"
        existing.source_event_id = None
        existing.provenance_parent_ids = []
        persisted_existing = self.store._obj_to_dict(existing)
        self.store.collection.get.return_value = {
            "ids": ["derived"],
            "metadatas": [persisted_existing],
        }

        upgraded = self.store.upgrade_legacy_provenance_scoped(
            "derived",
            existing,
            allowed_scopes=("owner",),
        )
        self.assertEqual(upgraded.origin_kind, "consolidation")
        self.assertEqual(upgraded.origin_source, "sleep")
        self.assertEqual(upgraded.provenance_parent_ids, ["p1", "p2", "p3"])
        written = self.store._dict_to_obj(
            self.store.collection.update.call_args.kwargs["metadatas"][0]
        )
        self.assertEqual(written.provenance_parent_ids, ["p1", "p2", "p3"])
        self.assertEqual(written.scope, "owner")

        for field_name, forged_value in (
            ("consolidation_parent_ids", ["attacker"]),
            ("origin_kind", "consolidation"),
            ("scope", "agent"),
        ):
            forged = _trace("derived")
            forged.consolidation_id = "batch-1"
            forged.consolidation_parent_ids = ["p1", "p2", "p3"]
            setattr(forged, field_name, forged_value)
            self.store.collection.update.reset_mock()
            with self.subTest(field=field_name), self.assertRaises(
                MemoryAccessError
            ):
                self.store.upgrade_legacy_provenance_scoped(
                    "derived",
                    forged,
                    allowed_scopes=("agent", "owner"),
                )
            self.store.collection.update.assert_not_called()

    def test_gc_is_scope_filtered_and_never_collects_legacy_unknown(self):
        legacy = _trace("legacy")
        legacy.privacy = "legacy_unknown"
        agent = _trace("agent", scope="agent")
        owner = _trace("owner", scope="owner")
        legacy.strength = agent.strength = owner.strength = 0.01
        self.store.collection.get.side_effect = [
            {
                "ids": ["legacy", "agent", "owner"],
                "metadatas": [
                    self.store._obj_to_dict(legacy),
                    self.store._obj_to_dict(agent),
                    self.store._obj_to_dict(owner),
                ],
            },
            {"ids": [], "metadatas": []},
        ]

        self.assertEqual(
            self.store.delete_weak_memories(
                allowed_scopes=("owner",),
            ),
            1,
        )
        first_where = self.store.collection.get.call_args_list[0].kwargs["where"]
        _assert_access_where(self, first_where, ("owner",))
        delete_kwargs = self.store.collection.delete.call_args.kwargs
        self.assertEqual(delete_kwargs["ids"], ["owner"])
        _assert_access_where(self, delete_kwargs["where"], ("owner",))

    def test_empty_delete_is_a_noop_at_vector_and_rest_layers(self):
        self.store.remove_batch_scoped([], allowed_scopes=("owner",))
        self.store.collection.delete.assert_not_called()

        client = Mock()
        wrapper = CollectionWrapper(client, "collection-id", "memory")
        self.assertIsNone(
            wrapper.delete(ids=[], where={"scope": {"$eq": "owner"}})
        )
        client._request.assert_not_called()

    def test_malformed_empty_migration_response_fails_closed(self):
        for malformed in ({}, {"ids": None, "metadatas": None}):
            with self.subTest(malformed=malformed):
                self.store.collection.reset_mock()
                self.store.collection.get.return_value = malformed
                with self.assertRaises(MemoryReadError) as raised:
                    self.store.migrate_legacy_metadata()
                self.assertEqual(
                    raised.exception.operation,
                    "migrate_legacy_metadata.decode",
                )
                self.store.collection.update.assert_not_called()


if __name__ == "__main__":
    unittest.main()
