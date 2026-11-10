import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from components.vector_store import MemoryStoreError
from core.engine.memory_ops import (
    MemoryOperationsController,
    _DREAM_OPERATION_TYPE,
    _build_dream_plan,
    _dream_consolidation_id,
    _dream_operation_id,
)
from core.memory import MemoryTrace, MemoryType
from core.operation_ledger import (
    OperationLedger,
    OperationStatus,
    QuarantineReason,
)


def _source(record_id, created_at):
    return MemoryTrace(
        id=record_id,
        content=f"source {record_id}",
        type=MemoryType.EPISODIC,
        valence=0.0,
        arousal=0.2,
        importance=0.5,
        strength=0.2,
        created_at=created_at,
        last_recalled=created_at,
        last_decayed_at=created_at,
        scope="owner",
        privacy="standard",
    )


class _DurableMemory:
    """Returns detached records so rollback cannot undo simulated disk writes."""

    def __init__(self, records):
        self.records = {
            str(trace.id): copy.deepcopy(trace)
            for trace in records
        }
        self.add_calls = 0
        self.update_calls = 0
        self.fail_add_before_once = False
        self.drop_last_add_once = False
        self.fail_update_before_once = False
        self.fail_update_after_first_once = False
        self.drop_last_update_once = False
        self.before_add = None

    def get_all(self):
        return [copy.deepcopy(trace) for trace in self.records.values()]

    def add_memories(self, traces):
        batch = list(traces)
        self.add_calls += 1
        if self.before_add is not None:
            self.before_add()
        if self.fail_add_before_once:
            self.fail_add_before_once = False
            raise MemoryStoreError("add_batch", cause_type="OSError")
        if self.drop_last_add_once:
            self.drop_last_add_once = False
            batch = batch[:-1]
        for trace in batch:
            self.records[str(trace.id)] = copy.deepcopy(trace)

    def update_memories(self, traces):
        batch = list(traces)
        self.update_calls += 1
        if self.fail_update_before_once:
            self.fail_update_before_once = False
            raise MemoryStoreError("update_meta_batch", cause_type="OSError")
        if self.fail_update_after_first_once:
            self.fail_update_after_first_once = False
            if batch:
                self.records[str(batch[0].id)] = copy.deepcopy(batch[0])
            raise MemoryStoreError("update_meta_batch", cause_type="OSError")
        if self.drop_last_update_once:
            self.drop_last_update_once = False
            batch = batch[:-1]
        for trace in batch:
            self.records[str(trace.id)] = copy.deepcopy(trace)

    def inject(self, trace):
        self.records[str(trace.id)] = copy.deepcopy(trace)

    def mutate_content(self, record_id, content):
        self.records[record_id].content = content


def _response(conclusion="a durable conclusion"):
    return json.dumps([{
        "conclusion": conclusion,
        "reasoning": "shared evidence",
        "tags": ["stable"],
    }])


def _controller(memory, ledger, response=None):
    controller = object.__new__(MemoryOperationsController)
    llm = SimpleNamespace(
        generate_text=Mock(return_value=(response or _response(), {})),
    )
    controller.engine = SimpleNamespace(
        memory=memory,
        llm=llm,
        operation_ledger=ledger,
    )
    return controller, llm


class DreamOperationLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.ledger = OperationLedger(
            Path(self.temporary.name) / "dream-ledger.sqlite3"
        )
        self.addCleanup(self.ledger.close)
        self.sources = [
            _source(f"source-{index}", float(index + 1))
            for index in range(3)
        ]
        self.memory = _DurableMemory(self.sources)

    def _only_record(self):
        records = self.ledger.list_recoverable(
            op_type=_DREAM_OPERATION_TYPE,
        )
        self.assertEqual(len(records), 1)
        return records[0]

    def test_ledger_is_durable_before_first_child_write(self):
        observed = []

        def inspect_ledger():
            record = self._only_record()
            observed.append(record.status)

        self.memory.before_add = inspect_ledger
        controller, _llm = _controller(self.memory, self.ledger)

        controller._dream_consolidation_phase()

        self.assertEqual(observed, [OperationStatus.APPLYING])
        parent_ids = [source.id for source in self.sources]
        record = self.ledger.get(
            _dream_operation_id(_dream_consolidation_id(parent_ids))
        )
        self.assertEqual(record.status, OperationStatus.COMMITTED)

    def test_crash_after_ledger_before_child_replays_without_llm(self):
        self.memory.fail_add_before_once = True
        controller, llm = _controller(self.memory, self.ledger)
        with self.assertRaises(MemoryStoreError):
            controller._dream_consolidation_phase()
        record = self._only_record()
        self.assertEqual(record.status, OperationStatus.APPLYING)
        self.assertEqual(llm.generate_text.call_count, 1)

        restarted, restarted_llm = _controller(
            self.memory,
            self.ledger,
            _response("different output must not be used"),
        )
        restarted._dream_consolidation_phase()

        restarted_llm.generate_text.assert_not_called()
        self.assertEqual(
            self.ledger.get(record.op_id).status,
            OperationStatus.COMMITTED,
        )
        self.assertTrue(all(
            self.memory.records[source.id].is_consolidated_source
            for source in self.sources
        ))

    def test_crash_after_children_before_marker_reuses_exact_children(self):
        self.memory.fail_update_before_once = True
        controller, _llm = _controller(self.memory, self.ledger)
        with self.assertRaises(MemoryStoreError):
            controller._dream_consolidation_phase()
        record = self._only_record()
        child_ids = {
            child["id"]
            for child in record.plan["children"]
        }
        self.assertTrue(child_ids.issubset(self.memory.records))
        self.assertEqual(self.memory.add_calls, 1)

        restarted, restarted_llm = _controller(self.memory, self.ledger)
        restarted._dream_consolidation_phase()

        restarted_llm.generate_text.assert_not_called()
        self.assertEqual(self.memory.add_calls, 1)
        self.assertEqual(
            self.ledger.get(record.op_id).status,
            OperationStatus.COMMITTED,
        )

    def test_acknowledged_partial_child_batch_stays_recoverable(self):
        self.memory.drop_last_add_once = True
        controller, llm = _controller(self.memory, self.ledger)

        with self.assertRaises(MemoryStoreError) as failure:
            controller._dream_consolidation_phase()

        self.assertEqual(failure.exception.cause_type, "IncompleteReadback")
        record = self._only_record()
        self.assertEqual(record.status, OperationStatus.APPLYING)
        self.assertEqual(llm.generate_text.call_count, 1)

        restarted, restarted_llm = _controller(self.memory, self.ledger)
        restarted._dream_consolidation_phase()

        restarted_llm.generate_text.assert_not_called()
        self.assertEqual(
            self.ledger.get(record.op_id).status,
            OperationStatus.COMMITTED,
        )
        self.assertTrue(all(
            child["id"] in self.memory.records
            for child in record.plan["children"]
        ))

    def test_acknowledged_partial_marker_batch_stays_recoverable(self):
        self.memory.drop_last_update_once = True
        controller, llm = _controller(self.memory, self.ledger)

        with self.assertRaises(MemoryStoreError) as failure:
            controller._dream_consolidation_phase()

        self.assertEqual(failure.exception.cause_type, "IncompleteReadback")
        record = self._only_record()
        self.assertEqual(record.status, OperationStatus.APPLYING)
        self.assertEqual(llm.generate_text.call_count, 1)

        restarted, restarted_llm = _controller(self.memory, self.ledger)
        restarted._dream_consolidation_phase()

        restarted_llm.generate_text.assert_not_called()
        self.assertTrue(all(
            self.memory.records[source.id].is_consolidated_source
            for source in self.sources
        ))
        self.assertEqual(
            self.ledger.get(record.op_id).status,
            OperationStatus.COMMITTED,
        )

    def test_partial_marker_crash_reuses_planned_exact_timestamp(self):
        self.memory.fail_update_after_first_once = True
        controller, _llm = _controller(self.memory, self.ledger)
        with self.assertRaises(MemoryStoreError):
            controller._dream_consolidation_phase()
        record = self._only_record()
        planned_timestamp = record.plan["consolidated_at"]
        first = self.memory.records[self.sources[0].id]
        self.assertEqual(first.consolidated_at, planned_timestamp)

        restarted, restarted_llm = _controller(self.memory, self.ledger)
        restarted._dream_consolidation_phase()

        restarted_llm.generate_text.assert_not_called()
        self.assertTrue(all(
            self.memory.records[source.id].consolidated_at
            == planned_timestamp
            for source in self.sources
        ))
        self.assertEqual(
            self.ledger.get(record.op_id).status,
            OperationStatus.COMMITTED,
        )

    def test_crash_after_marker_before_commit_only_finishes_cas(self):
        controller, _llm = _controller(self.memory, self.ledger)
        original_cas = self.ledger.compare_and_swap

        def crash_on_commit(*args, **kwargs):
            if OperationStatus(kwargs["new_status"]) is OperationStatus.COMMITTED:
                raise RuntimeError("simulated process crash")
            return original_cas(*args, **kwargs)

        with patch.object(
            self.ledger,
            "compare_and_swap",
            side_effect=crash_on_commit,
        ), self.assertRaises(RuntimeError):
            controller._dream_consolidation_phase()
        record = self._only_record()
        update_calls = self.memory.update_calls
        self.assertTrue(all(
            self.memory.records[source.id].is_consolidated_source
            for source in self.sources
        ))

        restarted, restarted_llm = _controller(self.memory, self.ledger)
        restarted._dream_consolidation_phase()

        restarted_llm.generate_text.assert_not_called()
        self.assertEqual(self.memory.update_calls, update_calls)
        self.assertEqual(
            self.ledger.get(record.op_id).status,
            OperationStatus.COMMITTED,
        )

    def test_child_collision_quarantines_without_hybridizing(self):
        self.memory.fail_add_before_once = True
        controller, _llm = _controller(self.memory, self.ledger)
        with self.assertRaises(MemoryStoreError):
            controller._dream_consolidation_phase()
        record = self._only_record()
        forged = MemoryTrace(**copy.deepcopy(record.plan["children"][0]))
        forged.content = "collision from another attempt"
        self.memory.inject(forged)

        restarted, restarted_llm = _controller(self.memory, self.ledger)
        restarted._dream_consolidation_phase()

        restarted_llm.generate_text.assert_not_called()
        terminal = self.ledger.get(record.op_id)
        self.assertEqual(terminal.status, OperationStatus.QUARANTINED)
        self.assertEqual(
            terminal.quarantine_reason,
            QuarantineReason.PRECONDITION_MISMATCH,
        )
        self.assertTrue(all(
            not self.memory.records[source.id].is_consolidated_source
            for source in self.sources
        ))

    def test_parent_fingerprint_change_quarantines_before_child(self):
        self.memory.fail_add_before_once = True
        controller, _llm = _controller(self.memory, self.ledger)
        with self.assertRaises(MemoryStoreError):
            controller._dream_consolidation_phase()
        record = self._only_record()
        self.memory.mutate_content(self.sources[1].id, "changed after planning")
        add_calls = self.memory.add_calls

        restarted, restarted_llm = _controller(self.memory, self.ledger)
        restarted._dream_consolidation_phase()

        restarted_llm.generate_text.assert_not_called()
        self.assertEqual(self.memory.add_calls, add_calls)
        terminal = self.ledger.get(record.op_id)
        self.assertEqual(terminal.status, OperationStatus.QUARANTINED)
        self.assertEqual(
            terminal.quarantine_reason,
            QuarantineReason.PRECONDITION_MISMATCH,
        )

    def test_invalid_second_insight_rejects_whole_batch(self):
        response = json.dumps([
            {
                "conclusion": "valid first insight",
                "reasoning": "valid reasoning",
                "tags": [],
            },
            {
                "conclusion": "invalid second insight",
                "reasoning": "valid reasoning",
                "tags": [False],
            },
        ])
        controller, _llm = _controller(self.memory, self.ledger, response)

        controller._dream_consolidation_phase()

        self.assertEqual(self.memory.add_calls, 0)
        self.assertEqual(self.memory.update_calls, 0)
        self.assertEqual(
            self.ledger.list_recoverable(op_type=_DREAM_OPERATION_TYPE),
            [],
        )

    def test_invalid_unicode_is_rejected_before_ledger_or_memory_write(self):
        response = json.dumps([{
            "conclusion": "poisoned \ud800 conclusion",
            "reasoning": "otherwise valid",
            "tags": [],
        }])
        controller, llm = _controller(self.memory, self.ledger, response)

        controller._dream_consolidation_phase()

        self.assertEqual(llm.generate_text.call_count, 1)
        self.assertEqual(self.memory.add_calls, 0)
        self.assertEqual(self.memory.update_calls, 0)
        self.assertEqual(
            self.ledger.list_recoverable(op_type=_DREAM_OPERATION_TYPE),
            [],
        )

    def test_canonical_parent_framing_has_no_delimiter_collision(self):
        first = ["a|b", "c", "d"]
        second = ["a", "b|c", "d"]
        self.assertEqual("|".join(first), "|".join(second))
        self.assertNotEqual(
            _dream_consolidation_id(first),
            _dream_consolidation_id(second),
        )

    def test_bad_pending_operation_does_not_starve_next_valid_plan(self):
        first_parents = self.sources
        second_parents = [
            _source(f"later-{index}", float(index + 10))
            for index in range(3)
        ]
        for trace in second_parents:
            self.memory.inject(trace)

        first_ids = [parent.id for parent in first_parents]
        first_consolidation = _dream_consolidation_id(first_ids)
        first_plan = _build_dream_plan(
            first_parents,
            [{
                "conclusion": "first planned conclusion",
                "reasoning": "first reason",
                "tags": [],
            }],
            first_consolidation,
            ("owner", "standard"),
        )
        # Recovery order is (created_at_ns, op_id). Pin distinct creation
        # times so the bad plan is scanned first even on coarse clocks
        # (Windows time_ns ticks in milliseconds and would tie both plans).
        with patch("core.operation_ledger.time.time_ns", return_value=1_000):
            first_record = self.ledger.create_or_get_plan(
                _dream_operation_id(first_consolidation),
                _DREAM_OPERATION_TYPE,
                first_plan,
            )
        second_ids = [parent.id for parent in second_parents]
        second_consolidation = _dream_consolidation_id(second_ids)
        second_plan = _build_dream_plan(
            second_parents,
            [{
                "conclusion": "second planned conclusion",
                "reasoning": "second reason",
                "tags": [],
            }],
            second_consolidation,
            ("owner", "standard"),
        )
        with patch("core.operation_ledger.time.time_ns", return_value=2_000):
            second_record = self.ledger.create_or_get_plan(
                _dream_operation_id(second_consolidation),
                _DREAM_OPERATION_TYPE,
                second_plan,
            )
        self.memory.mutate_content(first_parents[0].id, "bad precondition")
        controller, llm = _controller(self.memory, self.ledger)

        controller._dream_consolidation_phase()

        llm.generate_text.assert_not_called()
        self.assertEqual(
            self.ledger.get(first_record.op_id).status,
            OperationStatus.QUARANTINED,
        )
        self.assertEqual(
            self.ledger.get(second_record.op_id).status,
            OperationStatus.COMMITTED,
        )


if __name__ == "__main__":
    unittest.main()
