import hashlib
import json
import multiprocessing
import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from core.event_journal import (
    EventJournal,
    JournalContext,
    JournalCorruptionError,
    JournalIOError,
    JournalValidationError,
    RotatingEventJournal,
    activate_journal_context,
    canonical_json_bytes,
    compute_event_hash,
    record_current_event,
    reset_journal_context,
)


def _journal_process_writer(root, run_id, start, count, result_queue):
    """Top-level worker so Windows' spawn start method can import it."""

    try:
        journal = EventJournal(root, run_id=run_id, max_events=200)
        sequences = []
        for offset in range(count):
            index = start + offset
            event = journal.append(
                "interaction.accepted",
                {"operation": "interaction", "queue_depth": index},
                context=JournalContext(
                    correlation_id=f"process-{index}",
                    trace_id=f"process-{index}",
                    request_id=f"process-{index}",
                    source="test",
                ),
                outcome="accepted",
            )
            sequences.append(event.sequence)
        result_queue.put(("ok", sequences))
    except Exception as exc:  # pragma: no cover - surfaced in parent assertion
        result_queue.put(("error", repr(exc)))


class EventJournalM1Tests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "journal"

    def tearDown(self):
        self.temp_dir.cleanup()

    @staticmethod
    def context(*, private=False, correlation="request-1"):
        return JournalContext(
            correlation_id=correlation,
            trace_id=correlation,
            request_id=correlation,
            source="test",
            private_ephemeral=private,
        )

    def test_canonical_json_is_stable_and_rejects_nonfinite_numbers(self):
        self.assertEqual(
            canonical_json_bytes({"b": 2, "a": [3, 1]}),
            canonical_json_bytes({"a": [3, 1], "b": 2}),
        )
        with self.assertRaises(JournalValidationError):
            canonical_json_bytes({"bad": float("nan")})

    def test_append_restart_and_hash_chain_verify(self):
        journal = EventJournal(self.root)
        first = journal.append(
            "interaction.accepted",
            {"operation": "interaction", "queue_depth": 0},
            context=self.context(),
            outcome="accepted",
        )
        second = journal.append(
            "interaction.started",
            {"operation": "interaction", "queue_wait_ms": 1.25},
            context=self.context(),
            outcome="started",
            causation_id=first.event_id,
        )

        reopened = EventJournal(self.root, run_id=journal.run_id)
        third = reopened.append(
            "interaction.finished",
            {
                "operation": "interaction",
                "duration_ms": 2.5,
                "response_present": True,
            },
            context=self.context(),
            outcome="succeeded",
            causation_id=second.event_id,
        )

        events = list(reopened.iter_events())
        self.assertEqual([event.sequence for event in events], [1, 2, 3])
        self.assertEqual(third.previous_hash, second.event_hash)
        report = reopened.verify()
        self.assertTrue(report.valid, report.error)
        self.assertEqual(report.event_count, 3)

    def test_private_ephemeral_payload_and_content_hash_never_reach_disk(self):
        sentinel = "password-DO-NOT-PERSIST-93e3"
        sentinel_hash = hashlib.sha256(sentinel.encode("utf-8")).hexdigest()
        journal = EventJournal(self.root)

        event = journal.append(
            "interaction.accepted",
            {"operation": sentinel, "queue_depth": 999},
            context=self.context(private=True),
            outcome="accepted",
        )

        self.assertEqual(event.payload, {})
        self.assertEqual(event.privacy, "private_ephemeral")
        on_disk = b"".join(
            path.read_bytes() for path in self.root.rglob("*") if path.is_file()
        )
        self.assertNotIn(sentinel.encode("utf-8"), on_disk)
        self.assertNotIn(sentinel_hash.encode("ascii"), on_disk)

    def test_tamper_gap_and_filename_mismatch_are_detected(self):
        journal = EventJournal(self.root)
        for index in range(3):
            journal.append(
                "interaction.accepted",
                {"operation": "interaction", "queue_depth": index},
                context=self.context(correlation=f"request-{index}"),
                outcome="accepted",
            )

        second_path = sorted(journal.events_dir.glob("*.json"))[1]
        envelope = json.loads(second_path.read_text(encoding="utf-8"))
        envelope["payload"]["queue_depth"] = 999
        second_path.write_text(
            json.dumps(envelope, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        report = journal.verify()
        self.assertFalse(report.valid)
        self.assertEqual(report.corrupt_sequence, 2)

        # Restore by creating a new run, then remove the first sequence to make
        # a deterministic gap. Recovery must report it, never silently skip it.
        other = EventJournal(self.root)
        for index in range(2):
            other.append(
                "interaction.accepted",
                {"operation": "interaction", "queue_depth": index},
                context=self.context(correlation=f"gap-{index}"),
                outcome="accepted",
            )
        sorted(other.events_dir.glob("*.json"))[0].unlink()
        with self.assertRaises(JournalCorruptionError):
            list(other.iter_events())

    def test_closed_envelope_and_canonical_bytes_reject_covert_fields(self):
        sentinel = "raw-prompt-secret-DO-NOT-REPORT"

        cases = ("unknown", "missing", "duplicate", "noncanonical")
        for case in cases:
            with self.subTest(case=case):
                journal = EventJournal(self.root / case)
                journal.append(
                    "interaction.accepted",
                    {"operation": "interaction", "queue_depth": 0},
                    context=self.context(correlation=f"strict-{case}"),
                    outcome="accepted",
                )
                path = next(journal.events_dir.glob("*.json"))
                envelope = json.loads(path.read_text(encoding="utf-8"))

                if case == "unknown":
                    envelope["raw_prompt"] = sentinel
                    # Recompute the unauthenticated digest to prove that the
                    # closed envelope, not merely hash mismatch, rejects it.
                    envelope["event_hash"] = compute_event_hash(envelope)
                    raw = canonical_json_bytes(envelope)
                elif case == "missing":
                    envelope.pop("trace_id")
                    envelope["event_hash"] = compute_event_hash(envelope)
                    raw = canonical_json_bytes(envelope)
                elif case == "duplicate":
                    original = canonical_json_bytes(envelope)
                    raw = b'{"payload":null,' + original[1:]
                else:
                    raw = json.dumps(
                        envelope, ensure_ascii=False, indent=2
                    ).encode("utf-8")
                path.write_bytes(raw)

                report = journal.verify()
                self.assertFalse(report.valid)
                self.assertEqual(report.corrupt_sequence, 1)
                recovery = journal.recover()
                self.assertIsNotNone(recovery.corruption)
                self.assertNotIn(sentinel, report.error or "")
                self.assertNotIn(sentinel, recovery.corruption or "")

    def test_idempotent_retry_verifies_hmac_and_predecessor_chain(self):
        auth_key = b"deterministic-m1-auth-key-32bytes"
        event_id = "b" * 32
        journal = EventJournal(self.root / "auth", auth_key=auth_key)
        journal.append(
            "interaction.accepted",
            {"operation": "interaction", "queue_depth": 0},
            context=self.context(correlation="auth-retry"),
            outcome="accepted",
            event_id=event_id,
        )
        path = next(journal.events_dir.glob("*.json"))
        envelope = json.loads(path.read_text(encoding="utf-8"))
        envelope["occurred_at_ns"] += 1
        # Keep the old HMAC. The semantic retry data still matches, but the
        # committed envelope is no longer authenticated.
        path.write_bytes(canonical_json_bytes(envelope))
        with self.assertRaises(JournalCorruptionError):
            journal.append(
                "interaction.accepted",
                {"operation": "interaction", "queue_depth": 0},
                context=self.context(correlation="auth-retry"),
                outcome="accepted",
                event_id=event_id,
            )

        chained = EventJournal(self.root / "chain", auth_key=auth_key)
        first = chained.append(
            "interaction.accepted",
            {"operation": "interaction", "queue_depth": 0},
            context=self.context(correlation="chain-retry"),
            outcome="accepted",
            event_id="c" * 32,
        )
        second = chained.append(
            "interaction.started",
            {"operation": "interaction", "queue_wait_ms": 0.0},
            context=self.context(correlation="chain-retry"),
            outcome="started",
            causation_id=first.event_id,
            event_id="d" * 32,
        )
        second_path = sorted(chained.events_dir.glob("*.json"))[1]
        envelope = json.loads(second_path.read_text(encoding="utf-8"))
        envelope["previous_hash"] = "f" * 64
        envelope["event_hash"] = compute_event_hash(envelope, auth_key)
        second_path.write_bytes(canonical_json_bytes(envelope))
        with self.assertRaises(JournalCorruptionError):
            chained.append(
                "interaction.started",
                {"operation": "interaction", "queue_wait_ms": 0.0},
                context=self.context(correlation="chain-retry"),
                outcome="started",
                causation_id=first.event_id,
                event_id=second.event_id,
            )

    def test_concurrent_instances_allocate_one_contiguous_sequence(self):
        first = EventJournal(self.root, max_events=100)
        second = EventJournal(self.root, run_id=first.run_id, max_events=100)

        def append(index):
            writer = first if index % 2 else second
            return writer.append(
                "interaction.accepted",
                {"operation": "interaction", "queue_depth": index},
                context=self.context(correlation=f"parallel-{index}"),
                outcome="accepted",
            ).sequence

        with ThreadPoolExecutor(max_workers=8) as executor:
            sequences = list(executor.map(append, range(40)))

        self.assertEqual(sorted(sequences), list(range(1, 41)))
        self.assertTrue(first.verify().valid)

    def test_spawned_processes_share_sequence_and_hash_head_safely(self):
        journal = EventJournal(self.root, max_events=200)
        context = multiprocessing.get_context("spawn")
        result_queue = context.Queue()
        processes = [
            context.Process(
                target=_journal_process_writer,
                args=(str(self.root), journal.run_id, worker * 8, 8, result_queue),
            )
            for worker in range(3)
        ]
        for process in processes:
            process.start()
        results = [result_queue.get(timeout=20) for _ in processes]
        for process in processes:
            process.join(20)
            self.assertEqual(process.exitcode, 0)

        self.assertTrue(all(item[0] == "ok" for item in results), results)
        sequences = [sequence for _, batch in results for sequence in batch]
        self.assertEqual(sorted(sequences), list(range(1, 25)))
        reopened = EventJournal(
            self.root, run_id=journal.run_id, max_events=200, create=False
        )
        self.assertTrue(reopened.verify().valid)

    def test_atomic_publish_failure_is_typed_and_leaves_no_visible_event(self):
        journal = EventJournal(self.root)
        with patch("core.event_journal.os.replace", side_effect=OSError("disk")):
            with self.assertRaises(JournalIOError):
                journal.append(
                    "interaction.accepted",
                    {"operation": "interaction", "queue_depth": 0},
                    context=self.context(),
                    outcome="accepted",
                )

        self.assertEqual(list(journal.events_dir.glob("*.json")), [])
        self.assertEqual(list(journal.events_dir.glob(".tmp-*")), [])

    def test_orphan_temp_recovery_is_explicit_and_context_tracks_causation(self):
        journal = EventJournal(self.root)
        first = journal.append(
            "interaction.accepted",
            {"operation": "interaction", "queue_depth": 0},
            context=self.context(),
            outcome="accepted",
        )
        orphan = journal.events_dir / ".tmp-simulated-crash"
        orphan.write_bytes(b"partial")
        report = journal.recover(remove_orphan_temps=False)
        self.assertEqual(report.orphan_temps, 1)
        self.assertTrue(orphan.exists())

        token = activate_journal_context(
            journal, self.context(), causation_id=first.event_id
        )
        try:
            started = record_current_event(
                "interaction.started",
                {"operation": "interaction", "queue_wait_ms": 0.5},
                outcome="started",
            )
            finished = record_current_event(
                "interaction.finished",
                {
                    "operation": "interaction",
                    "duration_ms": 1.0,
                    "response_present": True,
                },
                outcome="succeeded",
            )
        finally:
            reset_journal_context(token)

        self.assertEqual(started.causation_id, first.event_id)
        self.assertEqual(finished.causation_id, started.event_id)
        removed = journal.recover(remove_orphan_temps=True)
        self.assertEqual(removed.removed_temps, 1)
        self.assertFalse(orphan.exists())

    def test_fail_open_wrapper_counts_failure(self):
        journal = EventJournal(self.root)
        event = journal.append_safe(
            "interaction.accepted",
            {"unexpected": "secret"},
            context=self.context(),
            outcome="accepted",
        )
        self.assertIsNone(event)
        self.assertEqual(journal.write_failures, 1)

    def test_rotating_writer_starts_a_new_run_at_the_hard_bound(self):
        journal = RotatingEventJournal(self.root, max_events=2)
        first_run = journal.run_id
        for index in range(3):
            journal.append(
                "interaction.accepted",
                {"operation": "interaction", "queue_depth": index},
                context=self.context(correlation=f"rotate-{index}"),
                outcome="accepted",
            )

        self.assertNotEqual(journal.run_id, first_run)
        self.assertEqual(len(EventJournal.list_run_ids(self.root)), 2)
        old = EventJournal(self.root, run_id=first_run, create=False)
        new = EventJournal(self.root, run_id=journal.run_id, create=False)
        self.assertEqual(len(list(old.iter_events())), 2)
        self.assertEqual(
            [event.event_type for event in new.iter_events()],
            ["journal.run_started", "interaction.accepted"],
        )

    def test_list_run_ids_skips_validly_named_partial_run_residue(self):
        complete = EventJournal(self.root)
        partial_id = f"{1:020d}-{'e' * 32}"
        partial = self.root / "runs" / partial_id
        (partial / "events").mkdir(parents=True)
        (partial / ".append.lock").touch()

        self.assertEqual(EventJournal.list_run_ids(self.root), (complete.run_id,))

    def test_list_run_ids_rejects_broken_control_file_on_committed_run(self):
        journal = EventJournal(self.root)
        journal.append(
            "interaction.accepted",
            {"operation": "interaction", "queue_depth": 0},
            context=self.context(correlation="committed-run"),
            outcome="accepted",
        )
        journal._lock_file.write_bytes(b"")

        with self.assertRaises(JournalCorruptionError):
            EventJournal.list_run_ids(self.root)


if __name__ == "__main__":
    unittest.main()
