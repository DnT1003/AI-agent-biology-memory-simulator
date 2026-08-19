import copy
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from components.vector_store import MemoryStoreError
from core.engine.memory_ops import (
    MemoryOperationsController,
    _REAPPRAISAL_OPERATION_TYPE,
    _reappraisal_child_id,
    _reappraisal_marker,
    _reappraisal_operation_id,
    _reappraisal_rekeyed_attempt_id,
)
from core.memory import MemoryTrace, MemoryType
from core.operation_ledger import (
    OperationLedger,
    OperationStatus,
    QuarantineReason,
)


def _parent(record_id, attempt_ids, *, created_at=1.0):
    return MemoryTrace(
        id=record_id,
        content=f"contradiction {record_id}",
        type=MemoryType.EPISODIC,
        valence=0.4,
        arousal=0.2,
        importance=0.7,
        strength=0.5,
        created_at=created_at,
        last_recalled=created_at,
        last_decayed_at=created_at,
        overlays=[_reappraisal_marker(attempt_id) for attempt_id in attempt_ids],
        scope="owner",
        privacy="standard",
        origin_kind="interaction",
        origin_source="test",
    )


def _decision(action="EVOLVE", belief="refined belief"):
    return json.dumps({
        "action": action,
        "reasoning": "stable evidence",
        "new_belief": belief if action == "EVOLVE" else "",
    })


class _DurableMemory:
    """Detached readbacks model process restart and durable side effects."""

    def __init__(self, records):
        self.records = {
            str(trace.id): copy.deepcopy(trace)
            for trace in records
        }
        self.add_calls = 0
        self.update_calls = 0
        self.upsert_calls = 0
        self.before_add = None
        self.fail_add_before_once = False
        self.drop_add_once = False
        self.fail_update_before_once = False
        self.fail_update_after_write_once = False
        self.drop_update_once = False

    def get_all(self):
        return [copy.deepcopy(trace) for trace in self.records.values()]

    def add_memory(self, trace):
        self.add_calls += 1
        if self.before_add is not None:
            self.before_add()
        if self.fail_add_before_once:
            self.fail_add_before_once = False
            raise MemoryStoreError("add", cause_type="OSError")
        if self.drop_add_once:
            self.drop_add_once = False
            return
        self.records[str(trace.id)] = copy.deepcopy(trace)

    def update_memory(self, trace):
        self.update_calls += 1
        if self.fail_update_before_once:
            self.fail_update_before_once = False
            raise MemoryStoreError("update", cause_type="OSError")
        if self.drop_update_once:
            self.drop_update_once = False
            return
        self.records[str(trace.id)] = copy.deepcopy(trace)
        if self.fail_update_after_write_once:
            self.fail_update_after_write_once = False
            raise MemoryStoreError("update", cause_type="OSError")

    def upsert_memory(self, trace):
        self.upsert_calls += 1
        self.records[str(trace.id)] = copy.deepcopy(trace)

    def inject(self, trace):
        self.records[str(trace.id)] = copy.deepcopy(trace)


def _controller(memory, ledger, responses=None):
    llm = SimpleNamespace(generate_text=Mock())
    if responses is None:
        llm.generate_text.return_value = (_decision(), {})
    elif isinstance(responses, list):
        llm.generate_text.side_effect = [
            (response, {}) for response in responses
        ]
    else:
        llm.generate_text.return_value = (responses, {})
    controller = object.__new__(MemoryOperationsController)
    controller.engine = SimpleNamespace(
        memory=memory,
        ego=SimpleNamespace(get_active_beliefs=Mock(return_value=[])),
        llm=llm,
        operation_ledger=ledger,
    )
    return controller, llm


class ReappraisalOperationLedgerTests(unittest.TestCase):
    ATTEMPT = "74bb6788-132b-475d-85f4-1942aa1e7825"

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.ledger = OperationLedger(
            Path(self.temporary.name) / "reappraisal-ledger.sqlite3"
        )
        self.addCleanup(self.ledger.close)
        self.parent = _parent("parent", [self.ATTEMPT])
        self.memory = _DurableMemory([self.parent])

    def _record(self, attempt_id=None):
        return self.ledger.get(_reappraisal_operation_id(
            attempt_id or self.ATTEMPT
        ))

    def test_tagging_uses_dedicated_marker_and_preserves_literal_user_text(self):
        added = []
        memory = SimpleNamespace(
            search_memories=Mock(return_value=[]),
            add_memory=Mock(side_effect=added.append),
            enforce_garbage_collection=Mock(),
        )
        controller = object.__new__(MemoryOperationsController)
        controller.engine = SimpleNamespace(
            memory=memory,
            ego=SimpleNamespace(
                get_active_beliefs=Mock(return_value=["stable belief"]),
            ),
            llm=SimpleNamespace(
                generate_text=Mock(return_value=("YES", {})),
            ),
        )
        controller.integrity_filter = SimpleNamespace(
            check_contradiction=Mock(return_value={
                "conflict": False,
                "impact_multiplier": 1.0,
                "reason": "",
            })
        )

        with patch("builtins.print"), patch(
            "core.engine.memory_ops.uuid.uuid4",
            return_value=uuid.UUID(self.ATTEMPT),
        ):
            controller.update_or_add_memory(
                "literal [ToReevaluate] user text",
                {
                    "internal_monologue": "thought",
                    "valence": 0.0,
                    "arousal": 0.2,
                    "importance": 0.5,
                },
            )

        self.assertEqual(len(added), 1)
        self.assertIn("literal [ToReevaluate] user text", added[0].content)
        self.assertEqual(added[0].overlays, [_reappraisal_marker(self.ATTEMPT)])

    def test_ledger_is_applying_before_first_child_write(self):
        observed = []

        def inspect_ledger():
            observed.append(self._record().status)

        self.memory.before_add = inspect_ledger
        controller, _llm = _controller(self.memory, self.ledger)

        with patch("builtins.print"):
            controller._cognitive_reappraisal_phase()

        self.assertEqual(observed, [OperationStatus.APPLYING])
        self.assertEqual(self._record().status, OperationStatus.COMMITTED)

    def test_crash_before_child_replays_plan_without_llm(self):
        self.memory.fail_add_before_once = True
        controller, llm = _controller(self.memory, self.ledger)
        with patch("builtins.print"), self.assertRaises(MemoryStoreError):
            controller._cognitive_reappraisal_phase()
        self.assertEqual(self._record().status, OperationStatus.APPLYING)
        llm.generate_text.assert_called_once()

        restarted, restarted_llm = _controller(
            self.memory,
            self.ledger,
            _decision("REJECT"),
        )
        with patch("builtins.print"):
            restarted._cognitive_reappraisal_phase()

        restarted_llm.generate_text.assert_not_called()
        self.assertEqual(self._record().status, OperationStatus.COMMITTED)
        self.assertIn(_reappraisal_child_id(self.ATTEMPT), self.memory.records)
        self.assertEqual(self.memory.add_calls, 2)

    def test_child_before_parent_crash_reuses_exact_child(self):
        self.memory.fail_update_before_once = True
        controller, _llm = _controller(self.memory, self.ledger)
        with patch("builtins.print"), self.assertRaises(MemoryStoreError):
            controller._cognitive_reappraisal_phase()
        child_id = _reappraisal_child_id(self.ATTEMPT)
        first_child = copy.deepcopy(self.memory.records[child_id])

        restarted, restarted_llm = _controller(self.memory, self.ledger)
        with patch("builtins.print"):
            restarted._cognitive_reappraisal_phase()

        restarted_llm.generate_text.assert_not_called()
        self.assertEqual(self.memory.add_calls, 1)
        self.assertEqual(self.memory.records[child_id].__dict__, first_child.__dict__)
        self.assertEqual(self._record().status, OperationStatus.COMMITTED)

    def test_parent_write_before_crash_only_commits_on_replay(self):
        self.memory.fail_update_after_write_once = True
        controller, _llm = _controller(self.memory, self.ledger)
        with patch("builtins.print"), self.assertRaises(MemoryStoreError):
            controller._cognitive_reappraisal_phase()
        self.assertNotIn(
            _reappraisal_marker(self.ATTEMPT),
            self.memory.records["parent"].overlays,
        )
        writes = (self.memory.add_calls, self.memory.update_calls)

        restarted, restarted_llm = _controller(self.memory, self.ledger)
        with patch("builtins.print"):
            restarted._cognitive_reappraisal_phase()

        restarted_llm.generate_text.assert_not_called()
        self.assertEqual((self.memory.add_calls, self.memory.update_calls), writes)
        self.assertEqual(self._record().status, OperationStatus.COMMITTED)

    def test_reject_decision_replays_exact_valence_without_llm(self):
        self.memory.fail_update_before_once = True
        controller, llm = _controller(
            self.memory,
            self.ledger,
            _decision("REJECT"),
        )
        with patch("builtins.print"), self.assertRaises(MemoryStoreError):
            controller._cognitive_reappraisal_phase()
        llm.generate_text.assert_called_once()

        restarted, restarted_llm = _controller(
            self.memory,
            self.ledger,
            _decision("SOFTEN"),
        )
        with patch("builtins.print"):
            restarted._cognitive_reappraisal_phase()

        restarted_llm.generate_text.assert_not_called()
        self.assertEqual(self.memory.records["parent"].valence, -0.5)
        self.assertEqual(self._record().status, OperationStatus.COMMITTED)

    def test_two_markers_create_distinct_operations_and_children(self):
        second = "8ce61e2d-c847-44b3-a40c-96696f23bd25"
        self.memory = _DurableMemory([
            _parent("parent", [self.ATTEMPT, second])
        ])
        controller, llm = _controller(
            self.memory,
            self.ledger,
            [_decision("EVOLVE", "first"), _decision("EVOLVE", "second")],
        )

        with patch("builtins.print"):
            controller._cognitive_reappraisal_phase()
            controller._cognitive_reappraisal_phase()

        self.assertEqual(llm.generate_text.call_count, 2)
        self.assertEqual(self._record().status, OperationStatus.COMMITTED)
        self.assertEqual(self._record(second).status, OperationStatus.COMMITTED)
        self.assertIn(_reappraisal_child_id(self.ATTEMPT), self.memory.records)
        self.assertIn(_reappraisal_child_id(second), self.memory.records)
        self.assertNotEqual(
            _reappraisal_child_id(self.ATTEMPT),
            _reappraisal_child_id(second),
        )

    def test_child_collision_is_quarantined_then_healthy_marker_progresses(self):
        healthy_attempt = "d06922bf-f17b-42eb-977f-fb7d496ad3a0"
        first = _parent("first", [self.ATTEMPT], created_at=1.0)
        healthy = _parent("healthy", [healthy_attempt], created_at=2.0)
        collision = MemoryTrace(
            id=_reappraisal_child_id(self.ATTEMPT),
            content="hostile collision",
            type=MemoryType.CORE,
            valence=0.0,
            arousal=0.2,
            importance=1.0,
        )
        self.memory = _DurableMemory([first, healthy, collision])
        controller, llm = _controller(self.memory, self.ledger)

        with patch("builtins.print"):
            controller._cognitive_reappraisal_phase()
            controller._cognitive_reappraisal_phase()

        bad = self._record()
        self.assertEqual(bad.status, OperationStatus.QUARANTINED)
        self.assertEqual(
            bad.quarantine_reason,
            QuarantineReason.PRECONDITION_MISMATCH,
        )
        self.assertEqual(self._record(healthy_attempt).status, OperationStatus.COMMITTED)
        self.assertEqual(llm.generate_text.call_count, 2)

    def test_invalid_unicode_response_creates_no_plan_or_memory_write(self):
        poisoned = json.dumps({
            "action": "EVOLVE",
            "reasoning": "stable",
            "new_belief": "poison \ud800",
        })
        controller, llm = _controller(self.memory, self.ledger, poisoned)

        with patch("builtins.print"):
            controller._cognitive_reappraisal_phase()

        llm.generate_text.assert_called_once()
        self.assertIsNone(self._record())
        self.assertEqual((self.memory.add_calls, self.memory.update_calls), (0, 0))
        self.assertIn(_reappraisal_marker(self.ATTEMPT), self.memory.records["parent"].overlays)

    def test_acknowledged_missing_child_stays_recoverable(self):
        self.memory.drop_add_once = True
        controller, _llm = _controller(self.memory, self.ledger)
        with patch("builtins.print"), self.assertRaises(MemoryStoreError) as failure:
            controller._cognitive_reappraisal_phase()

        self.assertEqual(failure.exception.cause_type, "IncompleteReadback")
        self.assertEqual(self._record().status, OperationStatus.APPLYING)

        restarted, restarted_llm = _controller(self.memory, self.ledger)
        with patch("builtins.print"):
            restarted._cognitive_reappraisal_phase()
        restarted_llm.generate_text.assert_not_called()
        self.assertEqual(self._record().status, OperationStatus.COMMITTED)

    def test_acknowledged_missing_parent_update_stays_recoverable(self):
        self.memory.drop_update_once = True
        controller, _llm = _controller(self.memory, self.ledger)
        with patch("builtins.print"), self.assertRaises(MemoryStoreError) as failure:
            controller._cognitive_reappraisal_phase()

        self.assertEqual(failure.exception.cause_type, "IncompleteReadback")
        self.assertEqual(self._record().status, OperationStatus.APPLYING)

        restarted, restarted_llm = _controller(self.memory, self.ledger)
        with patch("builtins.print"):
            restarted._cognitive_reappraisal_phase()
        restarted_llm.generate_text.assert_not_called()
        self.assertEqual(self._record().status, OperationStatus.COMMITTED)

    def test_legacy_marker_is_durably_migrated_before_analysis(self):
        legacy = _parent("legacy", [])
        legacy.content = "[ToReevaluate] legacy contradiction"
        self.memory = _DurableMemory([legacy])
        controller, llm = _controller(self.memory, self.ledger, "not json")

        with patch("builtins.print"):
            controller._cognitive_reappraisal_phase()

        persisted = self.memory.records["legacy"]
        self.assertEqual(persisted.content, "legacy contradiction")
        self.assertEqual(len(persisted.overlays), 1)
        self.assertTrue(persisted.overlays[0].startswith("[ToReevaluate:"))
        self.assertEqual(self.memory.upsert_calls, 1)
        llm.generate_text.assert_called_once()

    def test_conflicting_attempt_id_across_parents_rekeys_and_progresses(self):
        first = _parent("first", [self.ATTEMPT], created_at=1.0)
        second = _parent("second", [self.ATTEMPT], created_at=2.0)
        self.memory = _DurableMemory([first, second])
        controller, llm = _controller(
            self.memory,
            self.ledger,
            [_decision("EVOLVE", "first belief"), _decision("EVOLVE", "second belief")],
        )

        # Phase 1: commit first parent
        with patch("builtins.print"):
            controller._cognitive_reappraisal_phase()

        self.assertEqual(llm.generate_text.call_count, 1)
        self.assertEqual(self._record().status, OperationStatus.COMMITTED)
        self.assertNotIn(
            _reappraisal_marker(self.ATTEMPT),
            self.memory.records["first"].overlays,
        )
        self.assertIn(_reappraisal_child_id(self.ATTEMPT), self.memory.records)
        self.assertIn(
            _reappraisal_marker(self.ATTEMPT),
            self.memory.records["second"].overlays,
        )

        # Phase 2: only re-key second parent, llm_calls remains 1
        with patch("builtins.print"):
            controller._cognitive_reappraisal_phase()

        self.assertEqual(llm.generate_text.call_count, 1)
        rekeyed_attempt = _reappraisal_rekeyed_attempt_id(self.ATTEMPT, "second")
        self.assertNotIn(
            _reappraisal_marker(self.ATTEMPT),
            self.memory.records["second"].overlays,
        )
        self.assertIn(
            _reappraisal_marker(rekeyed_attempt),
            self.memory.records["second"].overlays,
        )
        self.assertIsNone(self._record(rekeyed_attempt))

        # Phase 3: commit second parent, llm_calls becomes 2
        with patch("builtins.print"):
            controller._cognitive_reappraisal_phase()

        self.assertEqual(llm.generate_text.call_count, 2)
        self.assertEqual(
            self._record(rekeyed_attempt).status,
            OperationStatus.COMMITTED,
        )
        self.assertIn(
            _reappraisal_child_id(rekeyed_attempt),
            self.memory.records,
        )
        self.assertNotEqual(
            _reappraisal_child_id(self.ATTEMPT),
            _reappraisal_child_id(rekeyed_attempt),
        )
        self.assertNotIn(
            _reappraisal_marker(self.ATTEMPT),
            self.memory.records["first"].overlays,
        )
        self.assertNotIn(
            _reappraisal_marker(rekeyed_attempt),
            self.memory.records["first"].overlays,
        )
        self.assertNotIn(
            _reappraisal_marker(self.ATTEMPT),
            self.memory.records["second"].overlays,
        )
        self.assertNotIn(
            _reappraisal_marker(rekeyed_attempt),
            self.memory.records["second"].overlays,
        )
        self.assertEqual(self.memory.records["first"].overlays, [])
        self.assertEqual(self.memory.records["second"].overlays, [])

    def test_rekey_preserves_other_overlays(self):
        first = _parent("first", [self.ATTEMPT], created_at=1.0)
        second = _parent("second", [self.ATTEMPT], created_at=2.0)
        second.overlays = ["other_tag_1", _reappraisal_marker(self.ATTEMPT), "other_tag_2"]
        self.memory = _DurableMemory([first, second])
        controller, _llm = _controller(
            self.memory,
            self.ledger,
            [_decision("EVOLVE", "first belief"), _decision("EVOLVE", "second belief")],
        )

        with patch("builtins.print"):
            controller._cognitive_reappraisal_phase()
            controller._cognitive_reappraisal_phase()

        rekeyed_attempt = _reappraisal_rekeyed_attempt_id(self.ATTEMPT, "second")
        self.assertEqual(
            self.memory.records["second"].overlays,
            ["other_tag_1", _reappraisal_marker(rekeyed_attempt), "other_tag_2"],
        )

    def test_rekey_readback_failure_retries_safely_without_llm(self):
        first = _parent("first", [self.ATTEMPT], created_at=1.0)
        second = _parent("second", [self.ATTEMPT], created_at=2.0)
        self.memory = _DurableMemory([first, second])
        controller, llm = _controller(
            self.memory,
            self.ledger,
            [_decision("EVOLVE", "first belief"), _decision("EVOLVE", "second belief")],
        )

        # Phase 1: commit first
        with patch("builtins.print"):
            controller._cognitive_reappraisal_phase()

        self.assertEqual(llm.generate_text.call_count, 1)

        # Phase 2: drop update once -> fails readback
        self.memory.drop_update_once = True
        with patch("builtins.print"), self.assertRaises(MemoryStoreError) as failure:
            controller._cognitive_reappraisal_phase()

        self.assertEqual(failure.exception.cause_type, "IncompleteReadback")
        self.assertEqual(llm.generate_text.call_count, 1)

        # Retry phase 2: rekey succeeds without calling LLM
        with patch("builtins.print"):
            controller._cognitive_reappraisal_phase()

        self.assertEqual(llm.generate_text.call_count, 1)
        rekeyed_attempt = _reappraisal_rekeyed_attempt_id(self.ATTEMPT, "second")
        self.assertIn(
            _reappraisal_marker(rekeyed_attempt),
            self.memory.records["second"].overlays,
        )

        # Phase 3: commit second
        with patch("builtins.print"):
            controller._cognitive_reappraisal_phase()

        self.assertEqual(llm.generate_text.call_count, 2)
        self.assertEqual(
            self._record(rekeyed_attempt).status,
            OperationStatus.COMMITTED,
        )

    def test_reappraisal_rekeyed_attempt_id_validation_and_determinism(self):
        from core.engine.memory_ops import _DreamPlanError
        rekeyed_1 = _reappraisal_rekeyed_attempt_id(self.ATTEMPT, "parent_a")
        rekeyed_2 = _reappraisal_rekeyed_attempt_id(self.ATTEMPT, "parent_a")
        rekeyed_b = _reappraisal_rekeyed_attempt_id(self.ATTEMPT, "parent_b")
        self.assertEqual(rekeyed_1, rekeyed_2)
        self.assertNotEqual(rekeyed_1, rekeyed_b)
        self.assertNotEqual(rekeyed_1, self.ATTEMPT)
        uuid.UUID(rekeyed_1)

        with self.assertRaises(_DreamPlanError):
            _reappraisal_rekeyed_attempt_id("not-a-uuid", "parent")
        with self.assertRaises(_DreamPlanError):
            _reappraisal_rekeyed_attempt_id(self.ATTEMPT, "")
        with self.assertRaises(_DreamPlanError):
            _reappraisal_rekeyed_attempt_id(self.ATTEMPT, "x" * 513)
        with self.assertRaises(_DreamPlanError):
            _reappraisal_rekeyed_attempt_id(self.ATTEMPT, "null\x00byte")

    def test_conflicting_attempt_id_with_duplicate_marker_on_second_parent_is_skipped(self):
        first = _parent("first", [self.ATTEMPT], created_at=1.0)
        second = _parent("second", [self.ATTEMPT, self.ATTEMPT], created_at=2.0)
        self.memory = _DurableMemory([first, second])
        controller, llm = _controller(
            self.memory,
            self.ledger,
            [_decision("EVOLVE", "first belief"), _decision("EVOLVE", "second belief")],
        )

        # Phase 1: commit first parent
        with patch("builtins.print"):
            controller._cognitive_reappraisal_phase()

        self.assertEqual(llm.generate_text.call_count, 1)
        self.assertEqual(self._record().status, OperationStatus.COMMITTED)
        update_calls_after_phase_1 = self.memory.update_calls
        second_overlays_before = list(self.memory.records["second"].overlays)

        # Phase 2: collision phase with duplicate marker on second parent
        with patch("builtins.print"):
            controller._cognitive_reappraisal_phase()

        # Second parent remains unchanged, no update increment, llm_calls remains 1, no replacement marker
        self.assertEqual(llm.generate_text.call_count, 1)
        self.assertEqual(self.memory.update_calls, update_calls_after_phase_1)
        self.assertEqual(
            self.memory.records["second"].overlays,
            second_overlays_before,
        )
        rekeyed_attempt = _reappraisal_rekeyed_attempt_id(self.ATTEMPT, "second")
        self.assertNotIn(
            _reappraisal_marker(rekeyed_attempt),
            self.memory.records["second"].overlays,
        )
        self.assertIsNone(self._record(rekeyed_attempt))


if __name__ == "__main__":
    unittest.main()
