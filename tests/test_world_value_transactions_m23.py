import copy
import json
import math
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import core.value_system as value_module
import core.world_graph as graph_module


class _LLM:
    def __init__(self, payload):
        self.payload = payload

    def generate_json(self, *args, **kwargs):
        return self.payload, {}


class _Cancellation(BaseException):
    pass


class WorldGraphTransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.path = Path(self.temp_dir.name) / "world_graph.json"

    def _graph(self):
        return graph_module.WorldGraph(str(self.path))

    @staticmethod
    def _relation(source="User", relation="trusts", target="Alice", valence=0.5):
        return {
            "source": source,
            "relation": relation,
            "target": target,
            "valence": valence,
        }

    def test_later_invalid_relation_causes_zero_mutation_and_no_write(self):
        graph = self._graph()
        graph.nodes.update({"Existing": {"type": "Entity"}})
        graph.edges.append({
            **self._relation("Existing", "knows", "User", 0.1),
            "timestamp": 123.0,
        })
        before_nodes = copy.deepcopy(graph.nodes)
        before_edges = copy.deepcopy(graph.edges)
        payload = {
            "relations": [
                self._relation(),
                self._relation("User", "rejects", "Mallory", True),
            ]
        }

        with patch.object(graph_module, "atomic_write_json") as writer:
            self.assertFalse(graph.update_from_text("private text", _LLM(payload)))

        self.assertEqual(graph.nodes, before_nodes)
        self.assertEqual(graph.edges, before_edges)
        writer.assert_not_called()

    def test_batch_save_failure_rolls_back_exactly_and_logs_only_type(self):
        graph = self._graph()
        graph.nodes.update({"Existing": {"type": "Entity"}})
        graph.edges.append({
            **self._relation("Existing", "knows", "User", 0.1),
            "timestamp": 123.0,
        })
        before_nodes = copy.deepcopy(graph.nodes)
        before_edges = copy.deepcopy(graph.edges)
        secret = "DO-NOT-LOG-private-relation"
        payload = {"relations": [self._relation(target=secret)]}

        with patch.object(graph_module.logger, "error") as log_error:
            with patch.object(
                graph_module,
                "atomic_write_json",
                side_effect=OSError(secret),
            ):
                self.assertFalse(graph.update_from_text("private text", _LLM(payload)))

        self.assertEqual(graph.nodes, before_nodes)
        self.assertEqual(graph.edges, before_edges)
        log_error.assert_called_once()
        call_args = log_error.call_args.args
        logs = call_args[0] % call_args[1:]
        self.assertIn("cause_type=OSError", logs)
        self.assertNotIn(secret, logs)
        self.assertNotIn("private text", logs)

    def test_add_existing_relation_is_durable_and_atomic(self):
        graph = self._graph()
        self.assertTrue(graph.add_relation("User", "trusts", "Alice", 0.5))
        self.assertTrue(graph.add_relation("User", "trusts", "Alice", -0.5))

        state = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(len(state["edges"]), 1)
        self.assertAlmostEqual(state["edges"][0]["valence"], 0.2)

    def test_valid_batch_commits_with_one_atomic_write(self):
        graph = self._graph()
        payload = {
            "relations": [
                self._relation(),
                self._relation("User", "knows", "Bob", 0.2),
            ]
        }
        real_writer = graph_module.atomic_write_json

        with patch.object(
            graph_module,
            "atomic_write_json",
            wraps=real_writer,
        ) as writer:
            self.assertTrue(graph.update_from_text("hello", _LLM(payload)))

        writer.assert_called_once()
        state = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(len(state["edges"]), 2)

    def test_writer_never_persists_state_its_reader_would_reject_for_size(self):
        graph = self._graph()
        before_nodes = copy.deepcopy(graph.nodes)
        before_edges = copy.deepcopy(graph.edges)

        with patch.object(graph, "_MAX_STATE_BYTES", 32), patch.object(
            graph_module, "atomic_write_json"
        ) as writer:
            self.assertFalse(graph.add_relation("User", "trusts", "Alice", 0.5))

        self.assertEqual(graph.nodes, before_nodes)
        self.assertEqual(graph.edges, before_edges)
        writer.assert_not_called()

    def test_cancellation_during_save_rolls_back_and_propagates(self):
        graph = self._graph()
        before_nodes = copy.deepcopy(graph.nodes)
        before_edges = copy.deepcopy(graph.edges)

        with patch.object(
            graph_module,
            "atomic_write_json",
            side_effect=_Cancellation(),
        ):
            with self.assertRaises(_Cancellation):
                graph.add_relation("User", "trusts", "Alice", 0.5)

        self.assertEqual(graph.nodes, before_nodes)
        self.assertEqual(graph.edges, before_edges)

    def test_malformed_later_edge_on_load_preserves_current_state(self):
        graph = self._graph()
        graph.nodes.update({"Existing": {"type": "Entity"}})
        graph.edges.append({
            **self._relation("Existing", "knows", "User", 0.1),
            "timestamp": 123.0,
        })
        before_nodes = copy.deepcopy(graph.nodes)
        before_edges = copy.deepcopy(graph.edges)
        self.path.write_text(
            json.dumps({
                "nodes": {
                    "User": {"type": "Entity"},
                    "Alice": {"type": "Entity"},
                    "Mallory": {"type": "Entity"},
                },
                "edges": [
                    {**self._relation(), "timestamp": 1.0},
                    {**self._relation(target="Mallory", valence=math.nan), "timestamp": 2.0},
                ],
            }),
            encoding="utf-8",
        )

        self.assertFalse(graph.load())
        self.assertEqual(graph.nodes, before_nodes)
        self.assertEqual(graph.edges, before_edges)

    def test_logger_failure_does_not_replace_validation_result(self):
        graph = self._graph()
        with patch.object(
            graph_module.logger,
            "error",
            side_effect=RuntimeError("logger unavailable"),
        ):
            self.assertFalse(graph.add_relation("", "trusts", "Alice", 0.5))
        self.assertEqual(graph.nodes, {})
        self.assertEqual(graph.edges, [])


class ValueSystemTransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.path = Path(self.temp_dir.name) / "values.json"
        self.values = value_module.ValueSystem(str(self.path))

    def test_save_failure_restores_user_values_and_propagates(self):
        self.values.user_values["Existing"] = 0.4
        before_core = copy.deepcopy(self.values.core_values)
        before_user = copy.deepcopy(self.values.user_values)

        with patch.object(
            value_module,
            "atomic_write_json",
            side_effect=OSError("private-state"),
        ):
            with self.assertRaises(OSError):
                self.values.update_user_value("New", 0.8)

        self.assertEqual(self.values.core_values, before_core)
        self.assertEqual(self.values.user_values, before_user)

    def test_invalid_numeric_inputs_never_mutate_or_write(self):
        before_core = copy.deepcopy(self.values.core_values)
        before_user = copy.deepcopy(self.values.user_values)
        invalid_cases = [True, math.nan, math.inf, -math.inf, 1.01, -1.01, "0.5"]

        with patch.object(value_module, "atomic_write_json") as writer:
            for invalid in invalid_cases:
                with self.subTest(invalid=invalid):
                    with self.assertRaises(ValueError):
                        self.values.update_user_value("Safety", invalid)

        self.assertEqual(self.values.core_values, before_core)
        self.assertEqual(self.values.user_values, before_user)
        writer.assert_not_called()

    def test_invalid_learning_rate_never_mutates_or_writes(self):
        before_user = copy.deepcopy(self.values.user_values)
        with patch.object(value_module, "atomic_write_json") as writer:
            with self.assertRaises(ValueError):
                self.values.update_user_value("Safety", 0.8, learning_rate=True)
        self.assertEqual(self.values.user_values, before_user)
        writer.assert_not_called()

    def test_malformed_later_value_on_load_preserves_both_maps(self):
        self.values.user_values["Existing"] = 0.4
        before_core = copy.deepcopy(self.values.core_values)
        before_user = copy.deepcopy(self.values.user_values)
        self.path.write_text(
            json.dumps({
                "core_values": {"Valid": 0.5},
                "user_values": {"First": 0.2, "Later": math.nan},
            }),
            encoding="utf-8",
        )

        self.assertFalse(self.values.load())
        self.assertEqual(self.values.core_values, before_core)
        self.assertEqual(self.values.user_values, before_user)

    def test_legacy_missing_map_preserves_current_defaults(self):
        before_core = copy.deepcopy(self.values.core_values)
        self.path.write_text(
            json.dumps({"user_values": {"Safety": 0.8}}),
            encoding="utf-8",
        )

        self.assertTrue(self.values.load())
        self.assertEqual(self.values.core_values, before_core)
        self.assertEqual(self.values.user_values, {"Safety": 0.8})

    def test_logger_failure_does_not_replace_load_result(self):
        self.path.write_text("not-json", encoding="utf-8")
        with patch.object(
            value_module.logger,
            "error",
            side_effect=RuntimeError("logger unavailable"),
        ):
            self.assertFalse(self.values.load())

    def test_concurrent_updates_do_not_lose_values_or_corrupt_disk(self):
        names = [f"Value-{index}" for index in range(24)]
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda name: self.values.update_user_value(name, 0.75), names))

        state = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(set(state["user_values"]), set(names))
        self.assertEqual(set(self.values.user_values), set(names))
        self.assertTrue(all(score == 0.75 for score in state["user_values"].values()))

    def test_batch_validates_every_name_before_first_mutation(self):
        self.values.user_values["Existing"] = 0.4
        before = dict(self.values.user_values)

        with patch.object(value_module, "atomic_write_json") as writer:
            with self.assertRaises(ValueError):
                self.values.update_user_values_batch([
                    ("Honesty", 0.8),
                    ("Broken\nName", 0.7),
                ])

        self.assertEqual(self.values.user_values, before)
        writer.assert_not_called()

    def test_batch_capacity_failure_is_all_or_nothing(self):
        self.values.user_values = {
            f"Value-{index}": 0.2
            for index in range(self.values._MAX_VALUES - 1)
        }
        before = dict(self.values.user_values)

        with patch.object(value_module, "atomic_write_json") as writer:
            with self.assertRaises(ValueError):
                self.values.update_user_values_batch([
                    ("Last-A", 0.8),
                    ("Last-B", 0.7),
                ])

        self.assertEqual(self.values.user_values, before)
        writer.assert_not_called()

    def test_batch_uses_one_write_and_rolls_back_exactly_on_failure(self):
        self.values.user_values = {"Existing": 0.4}
        with patch.object(value_module, "atomic_write_json") as writer:
            result = self.values.update_user_values_batch([
                ("Existing", 0.8),
                ("New", -0.7),
            ])

        self.assertAlmostEqual(result["Existing"], 0.48)
        self.assertEqual(result["New"], -0.7)
        writer.assert_called_once()
        persisted_values = writer.call_args.args[1]["user_values"]
        self.assertAlmostEqual(persisted_values["Existing"], 0.48)
        self.assertEqual(persisted_values["New"], -0.7)

        before = dict(self.values.user_values)
        with patch.object(
            value_module,
            "atomic_write_json",
            side_effect=OSError("private-state"),
        ):
            with self.assertRaises(OSError):
                self.values.update_user_values_batch([("Later", 0.9)])
        self.assertEqual(self.values.user_values, before)


if __name__ == "__main__":
    unittest.main()
