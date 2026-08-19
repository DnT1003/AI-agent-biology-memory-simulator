from __future__ import annotations

import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from config import Config
from core import replay
from core.event_journal import EventJournal, JournalContext
from core.state_projection import diff_projection


def _event(sequence: int, event_type: str, correlation: str = "req-1", **extra):
    value = {
        "schema": "aura.event/1",
        "sequence": sequence,
        "event_id": f"event-{sequence}",
        "event_type": event_type,
        "correlation_id": correlation,
        "payload": {},
    }
    value.update(extra)
    return value


class ReplayTests(unittest.TestCase):
    def test_replays_lifecycle_and_state_without_mutating_events(self):
        initial = {
            "schema_version": 1,
            "agent_state": "IDLE",
            "ego": {"energy": 0.8, "stress": 0.1},
            "stm": {"count": 0},
        }
        initial_hash = replay._projection_hash(initial)
        final = {
            "schema_version": 1,
            "agent_state": "THINKING",
            "ego": {"energy": 0.7, "stress": 0.1},
            "stm": {"count": 0},
        }
        patch = diff_projection(initial, final)
        final_hash = replay._projection_hash(final)
        events = [
            _event(1, "interaction.accepted"),
            _event(
                2,
                "state.snapshot",
                payload={"projection": initial, "projection_hash": initial_hash},
            ),
            _event(
                3,
                "state.delta",
                payload={
                    "before_hash": initial_hash,
                    "patch": patch,
                    "after_hash": final_hash,
                },
            ),
            _event(4, "interaction.started"),
            _event(5, "interaction.finished", outcome="succeeded"),
        ]
        untouched = copy.deepcopy(events)

        report = replay.replay_events(events, correlation_id="req-1")

        self.assertTrue(report.valid, report.violations)
        self.assertEqual(report.events_seen, 5)
        self.assertEqual(report.events_replayed, 5)
        self.assertEqual(report.outcomes, {"req-1": "succeeded"})
        self.assertEqual(report.final_hash, final_hash)
        self.assertEqual(report.final_projection, final)
        self.assertEqual(events, untouched)

    def test_missing_terminal_and_sequence_gap_are_typed_violations(self):
        report = replay.replay_events(
            [_event(4, "interaction.accepted"), _event(6, "interaction.started")]
        )

        self.assertFalse(report.valid)
        codes = {violation.code for violation in report.violations}
        self.assertIn("sequence.discontinuity", codes)
        self.assertIn("lifecycle.terminal_count", codes)
        self.assertTrue(all(isinstance(item, replay.ReplayViolation) for item in report.violations))

    def test_hash_chain_detects_tampering(self):
        first = _event(1, "runtime.started", correlation="runtime")
        first["event_hash"] = replay._event_hash(first)
        second = _event(
            2,
            "runtime.stopped",
            correlation="runtime",
            previous_hash=first["event_hash"],
            payload={"reason": "clean"},
        )
        second["event_hash"] = replay._event_hash(second)
        second["payload"]["reason"] = "tampered"

        report = replay.replay_events([first, second])

        self.assertFalse(report.valid)
        self.assertIn("hash.event_mismatch", {item.code for item in report.violations})

    def test_filter_projects_only_selected_correlation_but_checks_whole_stream(self):
        events = [
            _event(1, "interaction.accepted", "req-a"),
            _event(2, "interaction.started", "req-a"),
            _event(3, "interaction.finished", "req-a", outcome="succeeded"),
            _event(5, "interaction.accepted", "req-b"),
            _event(6, "interaction.failed", "req-b"),
        ]

        report = replay.replay_events(events, correlation_id="req-a")

        self.assertEqual(report.events_seen, 5)
        self.assertEqual(report.events_replayed, 3)
        self.assertEqual(report.outcomes, {"req-a": "succeeded"})
        self.assertIn("sequence.discontinuity", {item.code for item in report.violations})
        self.assertNotIn("req-b", report.outcomes)

    def test_invalid_state_delta_does_not_advance_projection(self):
        projection = {
            "schema_version": 1,
            "agent_state": "IDLE",
            "ego": {"energy": 0.8},
            "stm": {"count": 0},
        }
        projection_hash = replay._projection_hash(projection)
        events = [
            _event(1, "interaction.accepted"),
            _event(
                2,
                "state.snapshot",
                payload={"projection": projection, "projection_hash": projection_hash},
            ),
            _event(
                3,
                "state.delta",
                payload={
                    "before_hash": "wrong",
                    "patch": [{"op": "replace", "path": "/ego/energy", "value": 0.7}],
                    "after_hash": "also-wrong",
                },
            ),
            _event(4, "interaction.failed"),
        ]

        report = replay.replay_events(events)

        self.assertFalse(report.valid)
        self.assertEqual(report.final_projection, projection)
        self.assertEqual(report.final_hash, projection_hash)
        self.assertIn("state.before_hash_mismatch", {item.code for item in report.violations})

    def test_scenario_evaluator_is_exact_and_deterministic(self):
        report = replay.replay_events(
            [
                _event(1, "interaction.accepted"),
                _event(2, "interaction.started"),
                _event(3, "interaction.finished", outcome="succeeded"),
            ],
            correlation_id="req-1",
        )

        passing = replay.evaluate_scenario(
            report,
            {
                "event_kinds": [
                    "interaction.accepted",
                    "interaction.started",
                    "interaction.finished",
                ],
                "outcome": "succeeded",
            },
        )
        failing = replay.evaluate_scenario(report, {"outcome": "failed"})

        self.assertTrue(passing.passed)
        self.assertFalse(failing.passed)
        self.assertEqual(failing.violations[0].code, "scenario.outcome")

    def test_rejection_before_admission_is_a_complete_lifecycle(self):
        report = replay.replay_events(
            [_event(1, "interaction.finished", outcome="rejected")]
        )

        self.assertTrue(report.valid, report.violations)
        self.assertEqual(report.outcomes, {"req-1": "rejected"})

    def test_private_redacted_state_event_is_not_treated_as_corruption(self):
        report = replay.replay_events(
            [
                _event(1, "interaction.accepted", privacy="private_ephemeral"),
                _event(2, "state.snapshot", privacy="private_ephemeral"),
                _event(3, "interaction.started", privacy="private_ephemeral"),
                _event(
                    4,
                    "interaction.finished",
                    privacy="private_ephemeral",
                    outcome="succeeded",
                ),
            ]
        )

        self.assertTrue(report.valid, report.violations)
        self.assertIsNone(report.final_projection)

    def test_private_redacted_call_pairing_uses_order_without_persisted_ids(self):
        paired = replay.replay_events(
            [
                _event(
                    1,
                    "tool.started",
                    privacy="private_ephemeral",
                    outcome="started",
                ),
                _event(
                    2,
                    "tool.finished",
                    privacy="private_ephemeral",
                    outcome="succeeded",
                ),
            ]
        )
        orphan = replay.replay_events(
            [
                _event(
                    1,
                    "tool.finished",
                    privacy="private_ephemeral",
                    outcome="succeeded",
                )
            ]
        )

        self.assertTrue(paired.valid, paired.violations)
        self.assertFalse(orphan.valid)
        self.assertIn(
            "tool.finished_without_started",
            {item.code for item in orphan.violations},
        )

    def test_cli_reads_jsonl_without_importing_runtime(self):
        events = [
            _event(1, "interaction.accepted"),
            _event(2, "interaction.started"),
            _event(3, "interaction.finished", outcome="succeeded"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "journal.jsonl"
            path.write_text("".join(json.dumps(item) + "\n" for item in events), encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = replay.main([str(path), "--correlation", "req-1", "--json"])

        self.assertEqual(exit_code, 0)
        parsed = json.loads(output.getvalue())
        self.assertTrue(parsed["report"]["valid"])
        self.assertEqual(parsed["report"]["events_replayed"], 3)

    def test_cli_uses_exit_two_for_corrupt_jsonl_chain(self):
        events = [
            _event(1, "interaction.accepted"),
            _event(3, "interaction.finished", outcome="succeeded"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "journal.jsonl"
            path.write_text("".join(json.dumps(item) + "\n" for item in events), encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                exit_code = replay.main([str(path)])

        self.assertEqual(exit_code, 2)

    def test_cli_verifies_each_journal_run_before_aggregation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "journal"
            for correlation in ("req-a", "req-b"):
                journal = EventJournal(root)
                context = JournalContext(
                    correlation_id=correlation,
                    trace_id=correlation,
                    request_id=correlation,
                    source="test",
                )
                journal.append(
                    "interaction.accepted",
                    {"operation": "chat", "queue_depth": 0},
                    context=context,
                    outcome="accepted",
                )
                journal.append(
                    "interaction.started",
                    {"operation": "chat", "queue_wait_ms": 0.0},
                    context=context,
                    outcome="started",
                )
                journal.append(
                    "interaction.finished",
                    {
                        "operation": "chat",
                        "duration_ms": 1.0,
                        "response_present": True,
                    },
                    context=context,
                    outcome="succeeded",
                )
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = replay.main([str(root), "--json"])

        self.assertEqual(exit_code, 0)
        parsed = json.loads(output.getvalue())
        self.assertEqual(parsed["report"]["runs_replayed"], 2)
        self.assertEqual(parsed["report"]["events_seen"], 6)
        self.assertTrue(parsed["report"]["valid"])

    def test_cli_reads_hmac_journal_with_primary_or_alias_config_key(self):
        original_hmac = Config.EVENT_JOURNAL_HMAC_KEY
        original_auth = Config.EVENT_JOURNAL_AUTH_KEY
        key = b"replay-m1-test-auth-key"
        try:
            for use_alias in (False, True):
                with self.subTest(use_alias=use_alias), tempfile.TemporaryDirectory() as directory:
                    Config.EVENT_JOURNAL_HMAC_KEY = None if use_alias else key
                    Config.EVENT_JOURNAL_AUTH_KEY = key if use_alias else None
                    root = Path(directory) / "journal"
                    journal = EventJournal(root, auth_key=key)
                    context = JournalContext(
                        correlation_id="req-hmac",
                        trace_id="req-hmac",
                        request_id="req-hmac",
                        source="test",
                    )
                    journal.append(
                        "interaction.accepted",
                        {"operation": "chat", "queue_depth": 0},
                        context=context,
                        outcome="accepted",
                    )
                    journal.append(
                        "interaction.started",
                        {"operation": "chat", "queue_wait_ms": 0.0},
                        context=context,
                        outcome="started",
                    )
                    journal.append(
                        "interaction.finished",
                        {"operation": "chat", "response_present": True},
                        context=context,
                        outcome="succeeded",
                    )
                    output = io.StringIO()
                    with redirect_stdout(output):
                        exit_code = replay.main([str(root), "--json"])

                    self.assertEqual(exit_code, 0)
                    self.assertTrue(json.loads(output.getvalue())["report"]["valid"])
        finally:
            Config.EVENT_JOURNAL_HMAC_KEY = original_hmac
            Config.EVENT_JOURNAL_AUTH_KEY = original_auth

    def test_first_sequence_in_each_replayed_run_must_be_one(self):
        report = replay.replay_events([_event(2, "runtime.started", "runtime")])

        self.assertFalse(report.valid)
        self.assertIn(
            "sequence.first_not_one", {item.code for item in report.violations}
        )

    def test_success_and_failure_require_started_but_queued_cancel_does_not(self):
        for outcome in ("succeeded", "failed"):
            with self.subTest(outcome=outcome):
                report = replay.replay_events(
                    [
                        _event(1, "interaction.accepted"),
                        _event(2, "interaction.finished", outcome=outcome),
                    ]
                )
                self.assertFalse(report.valid)
                self.assertIn(
                    "lifecycle.started_count",
                    {item.code for item in report.violations},
                )

        cancelled = replay.replay_events(
            [
                _event(1, "interaction.accepted"),
                _event(2, "interaction.finished", outcome="cancelled"),
            ]
        )
        self.assertTrue(cancelled.valid, cancelled.violations)

    def test_terminal_kind_and_outcome_must_be_compatible(self):
        report = replay.replay_events(
            [
                _event(1, "interaction.accepted"),
                _event(2, "interaction.started"),
                _event(3, "interaction.failed", outcome="succeeded"),
            ]
        )

        self.assertFalse(report.valid)
        self.assertIn(
            "lifecycle.outcome_type_mismatch",
            {item.code for item in report.violations},
        )

    def test_inference_and_tool_calls_require_exact_start_finish_pairs(self):
        valid = replay.replay_events(
            [
                _event(1, "inference.started", payload={"call_id": "infer-1"}),
                _event(2, "inference.finished", payload={"call_id": "infer-1"}),
                _event(3, "tool.started", payload={"call_id": "tool-1"}),
                _event(4, "tool.finished", payload={"call_id": "tool-1"}),
            ]
        )
        self.assertTrue(valid.valid, valid.violations)

        invalid = replay.replay_events(
            [
                _event(1, "inference.started", payload={"call_id": "infer-2"}),
                _event(2, "tool.finished", payload={"call_id": "tool-2"}),
            ]
        )
        codes = {item.code for item in invalid.violations}
        self.assertIn("inference.finished_count", codes)
        self.assertIn("tool.finished_without_started", codes)
        self.assertIn("tool.started_count", codes)

    def test_private_call_lifecycle_without_persisted_call_id_is_replayable(self):
        report = replay.replay_events(
            [
                _event(1, "inference.started", privacy="private_ephemeral"),
                _event(2, "inference.finished", privacy="private_ephemeral"),
                _event(3, "tool.started", privacy="private_ephemeral"),
                _event(4, "tool.finished", privacy="private_ephemeral"),
            ]
        )

        self.assertTrue(report.valid, report.violations)

    def test_raw_hmac_requires_key_and_algorithm_switch_cannot_bypass(self):
        key = b"raw-jsonl-replay-key"
        authenticated = _event(
            1,
            "runtime.started",
            "runtime",
            hash_algorithm="hmac-sha256",
            previous_hash="0" * 64,
        )
        authenticated["event_hash"] = replay._event_hash(authenticated, key)

        unverified = replay.replay_events([authenticated])
        self.assertFalse(unverified.valid)
        self.assertIn(
            "hash.authentication_unverified",
            {item.code for item in unverified.violations},
        )
        self.assertTrue(
            replay.replay_events([authenticated], auth_key=key).valid
        )

        sha_event = _event(
            1,
            "runtime.started",
            "runtime",
            hash_algorithm="sha256",
            previous_hash="0" * 64,
        )
        sha_event["event_hash"] = replay._event_hash(sha_event)
        switched = copy.deepcopy(sha_event)
        switched["hash_algorithm"] = "hmac-sha256"
        switched_report = replay.replay_events([switched], auth_key=key)
        self.assertFalse(switched_report.valid)
        self.assertIn(
            "hash.event_mismatch",
            {item.code for item in switched_report.violations},
        )

    def test_cli_raw_hmac_without_configured_key_is_typed_corruption(self):
        original_hmac = Config.EVENT_JOURNAL_HMAC_KEY
        original_auth = Config.EVENT_JOURNAL_AUTH_KEY
        key = b"raw-export-key"
        try:
            Config.EVENT_JOURNAL_HMAC_KEY = None
            Config.EVENT_JOURNAL_AUTH_KEY = None
            event = _event(
                1,
                "runtime.started",
                "runtime",
                hash_algorithm="hmac-sha256",
                previous_hash="0" * 64,
            )
            event["event_hash"] = replay._event_hash(event, key)
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "journal.jsonl"
                path.write_text(json.dumps(event) + "\n", encoding="utf-8")
                output = io.StringIO()
                with redirect_stdout(output):
                    exit_code = replay.main([str(path), "--json"])
                Config.EVENT_JOURNAL_HMAC_KEY = key
                verified_output = io.StringIO()
                with redirect_stdout(verified_output):
                    verified_exit_code = replay.main([str(path), "--json"])
        finally:
            Config.EVENT_JOURNAL_HMAC_KEY = original_hmac
            Config.EVENT_JOURNAL_AUTH_KEY = original_auth

        self.assertEqual(exit_code, 2)
        parsed = json.loads(output.getvalue())
        self.assertIn(
            "hash.authentication_unverified",
            {item["code"] for item in parsed["report"]["violations"]},
        )
        self.assertEqual(verified_exit_code, 0)
        self.assertTrue(json.loads(verified_output.getvalue())["report"]["valid"])

    def test_delivery_ack_reconciles_across_runs_and_cli_accepts_runs_dir(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "journal"
            first = EventJournal(
                root,
                run_id="00000000000000000001-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            )
            second = EventJournal(
                root,
                run_id="00000000000000000002-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            )
            context = JournalContext(
                correlation_id="message-1",
                trace_id="message-1",
                request_id="message-1",
                source="web",
            )
            first.append(
                "delivery.durable",
                {"transport": "web", "message_id": "message-1"},
                context=context,
                outcome="durable",
            )
            second.append(
                "delivery.acked",
                {"transport": "web", "message_id": "message-1"},
                context=context,
                outcome="acked",
            )

            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = replay.main([str(root / "runs"), "--json"])

        self.assertEqual(exit_code, 0)
        parsed = json.loads(output.getvalue())
        self.assertTrue(parsed["report"]["valid"])
        self.assertEqual(parsed["report"]["runs_replayed"], 2)

    def test_delivery_ack_without_known_durable_is_a_typed_violation(self):
        report = replay.replay_events(
            [
                _event(
                    1,
                    "delivery.acked",
                    "message-1",
                    payload={"transport": "web", "message_id": "message-1"},
                )
            ]
        )

        self.assertFalse(report.valid)
        self.assertIn(
            "delivery.acked_without_durable",
            {item.code for item in report.violations},
        )


if __name__ == "__main__":
    unittest.main()
