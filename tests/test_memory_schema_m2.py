import json
import unittest
from unittest.mock import Mock, patch

from components.vector_store import (
    MemoryReadError,
    MemorySchemaError,
    VectorStore,
)
from core.memory import MemoryTrace, MemoryType


def _trace(record_id="record"):
    return MemoryTrace(
        id=record_id,
        content="private memory",
        type=MemoryType.EPISODIC,
        valence=0.1,
        arousal=0.2,
        importance=0.5,
        created_at=1_000.0,
        last_recalled=1_001.0,
        last_decayed_at=1_002.0,
    )


def _legacy_payload():
    return {
        "content": "legacy memory",
        "type": "episodic",
        "valence": 0.0,
        "arousal": 0.2,
        "importance": 0.5,
        "id": "legacy-id",
        "created_at": 100.0,
        "last_recalled": 101.0,
        "overlays": "first\n||\nsecond",
    }


class MemorySchemaV6Tests(unittest.TestCase):
    def setUp(self):
        self.store = object.__new__(VectorStore)

    def test_v6_roundtrip_is_lossless_and_uses_canonical_json_lists(self):
        trace = _trace("derived")
        trace.overlays = ["contains\n||\ndelimiter", "unicode-đ"]
        trace.consolidation_parent_ids = ["source-b", "source-a"]
        trace.scope = "agent"
        trace.privacy = "standard"
        trace.origin_kind = "interaction"
        trace.origin_source = "discord"
        trace.source_event_id = "event-1"
        trace.provenance_parent_ids = ["event-0", "memory-0"]

        metadata = self.store._obj_to_dict(trace)
        restored = self.store._dict_to_obj(metadata)

        self.assertEqual(metadata["schema_version"], "6")
        self.assertEqual(
            metadata["overlays"],
            json.dumps(trace.overlays, ensure_ascii=False, separators=(",", ":")),
        )
        self.assertEqual(
            metadata["consolidation_parent_ids"],
            '["source-b","source-a"]',
        )
        self.assertEqual(
            metadata["provenance_parent_ids"],
            '["event-0","memory-0"]',
        )
        self.assertEqual(restored.overlays, trace.overlays)
        self.assertEqual(restored.consolidation_parent_ids, trace.consolidation_parent_ids)
        self.assertEqual(restored.provenance_parent_ids, trace.provenance_parent_ids)
        self.assertEqual(restored.scope, "agent")
        self.assertEqual(restored.origin_source, "discord")
        self.assertEqual(restored.source_event_id, "event-1")

    def test_memory_trace_rejects_invalid_provenance(self):
        cases = (
            {"scope": "everyone"},
            {"privacy": "secret"},
            {"source_event_id": ""},
            {"origin_kind": " "},
            {"provenance_parent_ids": ["same", "same"]},
            {"provenance_parent_ids": [1]},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                MemoryTrace(
                    content="memory",
                    type=MemoryType.EPISODIC,
                    valence=0.0,
                    arousal=0.2,
                    importance=0.5,
                    **overrides,
                )

    def test_v1_through_v4_are_quarantined_with_best_effort_overlays(self):
        for version in range(1, 5):
            payload = _legacy_payload()
            metadata = (
                {"schema_version": str(version), "data": json.dumps(payload)}
                if version <= 3
                else {"schema_version": "4", **payload}
            )
            with self.subTest(version=version), patch(
                "components.vector_store.time.time", return_value=5_000.0
            ):
                restored = self.store._dict_to_obj(metadata)
            self.assertEqual(restored.scope, "owner")
            self.assertEqual(restored.privacy, "legacy_unknown")
            self.assertEqual(restored.origin_kind, "legacy")
            self.assertEqual(restored.overlays, ["first", "second"])
            self.assertEqual(restored.last_decayed_at, 5_000.0)
            self.assertTrue(restored._last_decay_checkpoint_pending)

    def test_v5_defaults_to_owner_standard_and_preserves_lineage(self):
        metadata = {
            "schema_version": "5",
            **_legacy_payload(),
            "consolidation_parent_ids": '["parent-1","parent-2"]',
        }

        restored = self.store._dict_to_obj(metadata)

        self.assertEqual(restored.scope, "owner")
        self.assertEqual(restored.privacy, "standard")
        self.assertEqual(restored.consolidation_parent_ids, ["parent-1", "parent-2"])

    def test_unknown_or_malformed_v6_fails_closed_without_payload(self):
        valid = self.store._obj_to_dict(_trace())
        cases = []
        unknown_version = dict(valid, schema_version="99")
        cases.append(unknown_version)
        malformed_list = dict(valid, overlays="private-payload-not-json")
        cases.append(malformed_list)
        unknown_field = dict(valid, private_payload="must-not-surface")
        cases.append(unknown_field)
        invalid_type = dict(valid, type="invented")
        cases.append(invalid_type)
        invalid_version_type = dict(valid, schema_version=6.0)
        cases.append(invalid_version_type)
        invalid_timestamp = dict(valid, timestamp=float("nan"))
        cases.append(invalid_timestamp)
        float_boolean = dict(valid, is_flashbulb=1.0)
        cases.append(float_boolean)
        mismatched_timestamp = dict(
            valid,
            timestamp=float(valid["created_at"]) + 1.0,
        )
        cases.append(mismatched_timestamp)

        for metadata in cases:
            with self.subTest(metadata_keys=sorted(metadata)), self.assertRaises(
                MemorySchemaError
            ) as raised:
                self.store._dict_to_obj(metadata)
            rendered = str(raised.exception)
            self.assertNotIn("private-payload", rendered)
            self.assertNotIn("must-not-surface", rendered)

    def test_get_all_never_silently_drops_a_corrupt_record(self):
        valid = self.store._obj_to_dict(_trace("valid"))
        corrupt = dict(valid, schema_version="77")
        self.store.collection = Mock()
        self.store.collection.get.return_value = {
            "metadatas": [valid, corrupt],
        }

        with self.assertRaises(MemorySchemaError):
            self.store.get_all_metadata()

    def test_backend_read_failures_are_typed_and_logs_are_metadata_safe(self):
        actions = []
        collection = Mock()
        collection.get.side_effect = RuntimeError("private backend message")
        store = object.__new__(VectorStore)
        store.collection = collection
        actions.append(("get_all_metadata", store.get_all_metadata))
        actions.append(("get_by_time_range", lambda: store.get_by_time_range(0, 1)))

        count_store = object.__new__(VectorStore)
        count_store.collection = Mock()
        count_store.collection.count.side_effect = RuntimeError("private count")
        actions.append(("search.count", lambda: count_store.search([0.1])))

        query_store = object.__new__(VectorStore)
        query_store.collection = Mock()
        query_store.collection.count.return_value = 1
        query_store.collection.query.side_effect = RuntimeError("private query")
        actions.append(("search.query", lambda: query_store.search([0.1])))

        for operation, action in actions:
            with self.subTest(operation=operation), patch(
                "components.vector_store.logger.error"
            ) as log_error, self.assertRaises(MemoryReadError) as raised:
                action()
            self.assertEqual(raised.exception.operation, operation)
            log_args = log_error.call_args.args
            logged = str(log_args[0]) % tuple(log_args[1:])
            self.assertNotIn("private", logged)

    def test_time_range_and_search_propagate_schema_corruption(self):
        corrupt = dict(self.store._obj_to_dict(_trace()), overlays="not-json")

        time_store = object.__new__(VectorStore)
        time_store.collection = Mock()
        time_store.collection.get.return_value = {"metadatas": [corrupt]}
        with self.assertRaises(MemorySchemaError):
            time_store.get_by_time_range(0, 2_000)

        search_store = object.__new__(VectorStore)
        search_store.collection = Mock()
        search_store.collection.count.return_value = 1
        search_store.collection.query.return_value = {
            "ids": [["record"]],
            "distances": [[0.2]],
            "metadatas": [[corrupt]],
        }
        with self.assertRaises(MemorySchemaError):
            search_store.search([0.1])


if __name__ == "__main__":
    unittest.main()
