import math
import os
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from config import Config
from core.operation_ledger import (
    MAX_PLAN_BYTES,
    MAX_PLAN_DEPTH,
    OperationConflictError,
    OperationCorruptionError,
    OperationLedger,
    OperationLedgerClosedError,
    OperationLedgerIOError,
    OperationPreconditionError,
    OperationStatus,
    OperationValidationError,
    QuarantineReason,
)


class OperationLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.path = Path(self.temp_dir.name) / "operation-ledger.sqlite3"

    def open_ledger(self) -> OperationLedger:
        ledger = OperationLedger(self.path)
        self.addCleanup(ledger.close)
        return ledger

    def test_config_path_is_absolute_and_under_output_dir(self):
        output_dir = Path(Config.OUTPUT_DIR)
        if not output_dir.is_absolute():
            output_dir = Path(Config.BASE_DIR) / output_dir

        configured = Path(Config.OPERATION_LEDGER_FILE)
        self.assertTrue(configured.is_absolute())
        self.assertEqual(configured.parent.resolve(), output_dir.resolve())
        self.assertEqual(Config.OPERATION_LEDGER_PATH, Config.OPERATION_LEDGER_FILE)

    def test_database_uses_wal_full_sync_version_and_recovery_indexes(self):
        ledger = self.open_ledger()
        connection = sqlite3.connect(self.path)
        self.addCleanup(connection.close)

        self.assertEqual(
            connection.execute("PRAGMA journal_mode").fetchone()[0].lower(),
            "wal",
        )
        self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
        # SQLite reports FULL as 2.
        self.assertEqual(connection.execute("PRAGMA synchronous").fetchone()[0], 2)
        indexes = {
            row[1]
            for row in connection.execute("PRAGMA index_list(operations)")
        }
        self.assertIn("idx_operations_status_created", indexes)
        self.assertIn("idx_operations_type_status_created", indexes)
        ledger.checkpoint()

    def test_create_or_get_is_exact_idempotent_and_plan_is_detached(self):
        ledger = self.open_ledger()
        source = {"z": [1, True, None], "a": {"value": 2.5}}
        first = ledger.create_or_get_plan("dream:001", "dream.consolidate", source)
        source["z"][0] = 99
        first.plan["z"][0] = 77

        second = ledger.create_or_get_plan(
            "dream:001",
            "dream.consolidate",
            {"a": {"value": 2.5}, "z": [1, True, None]},
        )

        self.assertEqual(second.status, OperationStatus.PLANNED)
        self.assertEqual(second.revision, 0)
        self.assertEqual(second.plan, {"a": {"value": 2.5}, "z": [1, True, None]})
        self.assertEqual(first.plan_json, second.plan_json)
        self.assertEqual(first.plan_sha256, second.plan_sha256)
        self.assertEqual(first.created_at_ns, second.created_at_ns)

    def test_same_id_with_different_type_or_plan_is_a_typed_conflict(self):
        ledger = self.open_ledger()
        original = ledger.create_or_get_plan("op-1", "dream", {"child": "a"})

        with self.assertRaises(OperationConflictError):
            ledger.create_or_get_plan("op-1", "belief", {"child": "a"})
        with self.assertRaises(OperationConflictError):
            ledger.create_or_get_plan("op-1", "dream", {"child": "b"})

        current = ledger.get("op-1")
        self.assertEqual(current.plan_sha256, original.plan_sha256)
        self.assertEqual(current.revision, 0)

    def test_hash_binds_plan_to_operation_identity(self):
        ledger = self.open_ledger()
        left = ledger.create_or_get_plan("op-left", "dream", {"value": 1})
        right = ledger.create_or_get_plan("op-right", "dream", {"value": 1})
        changed_type = ledger.create_or_get_plan("op-third", "belief", {"value": 1})

        self.assertNotEqual(left.plan_sha256, right.plan_sha256)
        self.assertNotEqual(left.plan_sha256, changed_type.plan_sha256)

    def test_cas_rejects_stale_revision_and_illegal_state_skip(self):
        ledger = self.open_ledger()
        ledger.create_or_get_plan("op-cas", "dream", {"value": 1})

        with self.assertRaises(OperationPreconditionError):
            ledger.compare_and_swap(
                "op-cas",
                expected_revision=0,
                expected_status="planned",
                new_status="committed",
            )
        self.assertTrue(
            ledger.compare_and_swap(
                "op-cas",
                expected_revision=0,
                expected_status="planned",
                new_status="applying",
            )
        )
        self.assertFalse(
            ledger.compare_and_swap(
                "op-cas",
                expected_revision=0,
                expected_status="planned",
                new_status="applying",
            )
        )
        applying = ledger.get("op-cas")
        self.assertEqual(applying.status, OperationStatus.APPLYING)
        self.assertEqual(applying.revision, 1)

    def test_concurrent_cas_has_exactly_one_winner(self):
        ledger = self.open_ledger()
        ledger.create_or_get_plan("op-race", "dream", {"value": 1})
        worker_count = 16
        barrier = threading.Barrier(worker_count)
        results: list[bool] = []
        failures: list[BaseException] = []
        result_lock = threading.Lock()

        def worker():
            try:
                barrier.wait(timeout=5)
                result = ledger.compare_and_swap(
                    "op-race",
                    expected_revision=0,
                    expected_status="planned",
                    new_status="applying",
                )
                with result_lock:
                    results.append(result)
            except BaseException as exc:
                with result_lock:
                    failures.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(worker_count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(failures, [])
        self.assertEqual(results.count(True), 1)
        self.assertEqual(results.count(False), worker_count - 1)
        self.assertEqual(ledger.get("op-race").revision, 1)

    def test_restart_recovers_exact_plan_and_applying_state(self):
        ledger = OperationLedger(self.path)
        created = ledger.create_or_get_plan(
            "sleep:2026-01-01",
            "sleep.maintenance",
            {"phases": ["dream", "decay"], "version": 1},
        )
        ledger.compare_and_swap(
            created.op_id,
            expected_revision=0,
            expected_status="planned",
            new_status="applying",
        )
        ledger.close()

        reopened = self.open_ledger()
        recovered = reopened.list_recoverable()
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0].op_id, created.op_id)
        self.assertEqual(recovered[0].status, OperationStatus.APPLYING)
        self.assertEqual(recovered[0].revision, 1)
        self.assertEqual(
            recovered[0].plan,
            {"phases": ["dream", "decay"], "version": 1},
        )
        self.assertEqual(recovered[0].plan_sha256, created.plan_sha256)

    def test_recovery_order_is_created_then_id_and_excludes_terminal(self):
        ledger = self.open_ledger()
        with patch("core.operation_ledger.time.time_ns", return_value=1234):
            for op_id in ("op-z", "op-a", "op-m"):
                ledger.create_or_get_plan(op_id, "dream", {"id": op_id})
        ledger.compare_and_swap(
            "op-m",
            expected_revision=0,
            expected_status="planned",
            new_status="applying",
        )
        ledger.compare_and_swap(
            "op-m",
            expected_revision=1,
            expected_status="applying",
            new_status="committed",
        )

        self.assertEqual(
            [record.op_id for record in ledger.list_recoverable()],
            ["op-a", "op-z"],
        )

    def test_recovery_filter_prevents_cross_workflow_limit_starvation(self):
        ledger = self.open_ledger()
        with patch("core.operation_ledger.time.time_ns", return_value=1234):
            ledger.create_or_get_plan("reappraisal-a", "reappraisal", {"step": 1})
            ledger.create_or_get_plan("reappraisal-b", "reappraisal", {"step": 2})
            dream = ledger.create_or_get_plan("dream-z", "dream", {"step": 3})

        recovered = ledger.list_recoverable(op_type="dream", limit=1)

        self.assertEqual([record.op_id for record in recovered], [dream.op_id])
        self.assertEqual(
            [record.op_id for record in ledger.list_recoverable(limit=2)],
            ["dream-z", "reappraisal-a"],
        )

    def test_one_byte_payload_tamper_fails_closed_and_can_be_quarantined(self):
        ledger = self.open_ledger()
        ledger.create_or_get_plan("op-tamper", "dream", {"step": "alpha"})
        connection = sqlite3.connect(self.path)
        self.addCleanup(connection.close)
        connection.execute(
            "UPDATE operations SET plan_json = replace(plan_json, 'alpha', 'bravo') "
            "WHERE op_id = 'op-tamper'"
        )
        connection.commit()

        with self.assertRaises(OperationCorruptionError):
            ledger.get("op-tamper")
        with self.assertRaises(OperationCorruptionError):
            ledger.create_or_get_plan("op-tamper", "dream", {"step": "alpha"})

        self.assertTrue(
            ledger.quarantine(
                "op-tamper",
                reason=QuarantineReason.CORRUPTION,
                expected_revision=0,
                expected_status="planned",
            )
        )
        self.assertEqual(ledger.list_recoverable(), [])

    def test_corrupt_recoverable_row_is_quarantined_without_blocking_healthy_peer(self):
        ledger = self.open_ledger()
        ledger.create_or_get_plan("bad-row", "dream", {"step": "alpha"})
        healthy = ledger.create_or_get_plan("healthy-row", "dream", {"step": "safe"})
        connection = sqlite3.connect(self.path)
        self.addCleanup(connection.close)
        connection.execute(
            "UPDATE operations SET plan_json = replace(plan_json, 'alpha', 'bravo') "
            "WHERE op_id = 'bad-row'"
        )
        connection.commit()

        # The requested limit counts healthy results, not corrupt rows scanned.
        recovered = ledger.list_recoverable(limit=1)

        self.assertEqual([record.op_id for record in recovered], [healthy.op_id])
        status, revision, reason = connection.execute(
            "SELECT status, revision, quarantine_reason FROM operations "
            "WHERE op_id = 'bad-row'"
        ).fetchone()
        self.assertEqual(status, "quarantined")
        self.assertEqual(revision, 1)
        self.assertEqual(reason, "corruption")

    def test_quarantine_is_exact_and_only_accepts_bounded_reasons(self):
        ledger = self.open_ledger()
        ledger.create_or_get_plan("op-quarantine", "dream", {"value": 1})

        self.assertFalse(
            ledger.quarantine(
                "op-quarantine",
                reason="precondition_mismatch",
                expected_revision=1,
            )
        )
        with self.assertRaises(OperationValidationError):
            ledger.quarantine("op-quarantine", reason="transient_io_failure")
        self.assertTrue(
            ledger.quarantine(
                "op-quarantine",
                reason="precondition_mismatch",
                expected_revision=0,
                expected_status="planned",
            )
        )
        record = ledger.get("op-quarantine")
        self.assertEqual(record.status, OperationStatus.QUARANTINED)
        self.assertEqual(record.revision, 1)
        self.assertEqual(
            record.quarantine_reason,
            QuarantineReason.PRECONDITION_MISMATCH,
        )

    def test_purge_removes_old_terminal_rows_but_never_active_rows(self):
        ledger = self.open_ledger()
        for op_id in ("planned", "applying", "committed", "quarantined"):
            ledger.create_or_get_plan(op_id, "test", {"id": op_id})
        ledger.compare_and_swap(
            "applying",
            expected_revision=0,
            expected_status="planned",
            new_status="applying",
        )
        ledger.compare_and_swap(
            "committed",
            expected_revision=0,
            expected_status="planned",
            new_status="applying",
        )
        ledger.compare_and_swap(
            "committed",
            expected_revision=1,
            expected_status="applying",
            new_status="committed",
        )
        ledger.quarantine(
            "quarantined",
            reason="corruption",
            expected_revision=0,
        )

        purged = ledger.purge_terminal(
            0,
            now_ns=2**63 - 1,
            limit=10,
        )

        self.assertEqual(purged, 2)
        self.assertIsNone(ledger.get("committed"))
        self.assertIsNone(ledger.get("quarantined"))
        self.assertEqual(
            [record.op_id for record in ledger.list_recoverable()],
            ["planned", "applying"],
        )

    def test_plan_limits_nan_paths_depth_and_numeric_bools_fail_closed(self):
        ledger = self.open_ledger()

        invalid_plans = (
            {"number": math.nan},
            {"number": math.inf},
            {"path": Path("secret.txt")},
            {"payload": "x" * (MAX_PLAN_BYTES + 1)},
        )
        for index, plan in enumerate(invalid_plans):
            with self.subTest(index=index):
                with self.assertRaises(OperationValidationError):
                    ledger.create_or_get_plan(f"bad-{index}", "test", plan)

        too_deep: dict[str, object] = {}
        cursor = too_deep
        for _ in range(MAX_PLAN_DEPTH + 1):
            child: dict[str, object] = {}
            cursor["child"] = child
            cursor = child
        with self.assertRaises(OperationValidationError):
            ledger.create_or_get_plan("too-deep", "test", too_deep)

        with self.assertRaises(OperationValidationError):
            ledger.create_or_get_plan("../escape", "test", {"value": 1})
        ledger.create_or_get_plan("strict-numeric", "test", {"flag": True})
        with self.assertRaises(OperationValidationError):
            ledger.compare_and_swap(
                "strict-numeric",
                expected_revision=True,
                expected_status="planned",
                new_status="applying",
            )
        with self.assertRaises(OperationValidationError):
            ledger.list_recoverable(limit=True)
        with self.assertRaises(OperationValidationError):
            ledger.list_recoverable(op_type="../escape")
        with self.assertRaises(OperationValidationError):
            ledger.purge_terminal(True)
        # An enormous retention is treated as older than the whole epoch-to-now
        # interval rather than overflowing during nanosecond conversion.
        self.assertEqual(ledger.purge_terminal(10**10_000), 0)
        with self.assertRaises(OperationValidationError):
            ledger.compare_and_swap(
                "strict-numeric",
                expected_revision=2**63,
                expected_status="planned",
                new_status="applying",
            )

    def test_out_of_range_clock_fails_before_sqlite_can_coerce_it(self):
        ledger = self.open_ledger()
        for index, timestamp in enumerate((2**63 - 1, 2**63)):
            with self.subTest(timestamp=timestamp):
                with patch(
                    "core.operation_ledger.time.time_ns",
                    return_value=timestamp,
                ):
                    with self.assertRaises(OperationLedgerIOError):
                        ledger.create_or_get_plan(
                            f"bad-clock-{index}",
                            "test",
                            {"value": 1},
                        )
                self.assertIsNone(ledger.get(f"bad-clock-{index}"))

    def test_checkpoint_close_and_context_manager_contract(self):
        with OperationLedger(self.path) as ledger:
            ledger.create_or_get_plan("op-close", "test", {"value": 1})
            result = ledger.checkpoint("PASSIVE")
            self.assertGreaterEqual(result.busy, 0)
            self.assertGreaterEqual(result.log_frames, 0)
            self.assertGreaterEqual(result.checkpointed_frames, 0)

        ledger.close()
        with self.assertRaises(OperationLedgerClosedError):
            ledger.get("op-close")

    def test_close_still_closes_when_checkpoint_reports_an_error(self):
        ledger = OperationLedger(self.path)
        with patch.object(
            ledger,
            "checkpoint",
            side_effect=OperationLedgerIOError("checkpoint failed"),
        ):
            with self.assertRaises(OperationLedgerIOError):
                ledger.close()
        with self.assertRaises(OperationLedgerClosedError):
            ledger.get("missing")
        ledger.close()

    def test_unsupported_existing_schema_fails_closed(self):
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA user_version=99")
        connection.close()

        with self.assertRaises(OperationCorruptionError):
            OperationLedger(self.path)


if __name__ == "__main__":
    unittest.main()
