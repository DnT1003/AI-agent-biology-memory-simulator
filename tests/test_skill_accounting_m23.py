import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from core.event_journal import EventJournal, JournalContext, journal_context
from core.skills import Skill, SkillRegistry


class SkillAccountingTransactionM23Tests(unittest.TestCase):
    @staticmethod
    def _context(correlation):
        return JournalContext(
            correlation_id=correlation,
            trace_id=correlation,
            request_id=correlation,
            source="test",
        )

    def test_committed_tool_success_survives_accounting_save_failure(self):
        calls = []
        logger = Mock()
        registry = SkillRegistry()

        def committed_side_effect(argument):
            calls.append(argument)
            return "committed-result"

        skill = Skill("counter", "Counter", "counter | value", committed_side_effect)
        skill.mastery = 0.6
        skill.rust_level = 0.25
        skill.last_used = 123.0
        registry.register(skill)
        accounting_before = (skill.mastery, skill.rust_level, skill.last_used)
        error_secret = "storage-path-secret-m23"

        with TemporaryDirectory() as temp_dir:
            journal_root = Path(temp_dir) / "journal"
            journal = EventJournal(journal_root)
            with (
                journal_context(journal, self._context("accounting-success")),
                patch.object(
                    registry,
                    "_save_unsafe",
                    side_effect=OSError(error_secret),
                ) as save,
                patch("core.logger.get_logger", return_value=logger),
                patch("core.skills.time.time", return_value=456.0),
            ):
                result = registry.execute("counter", "increment-once")
            events = list(journal.iter_events())
            disk_bytes = b"".join(
                path.read_bytes()
                for path in journal_root.rglob("*")
                if path.is_file()
            )

        self.assertEqual(result, "committed-result")
        self.assertEqual(calls, ["increment-once"])
        self.assertEqual(
            (skill.mastery, skill.rust_level, skill.last_used),
            accounting_before,
        )
        save.assert_called_once_with()
        self.assertEqual(
            [event.event_type for event in events],
            ["tool.started", "tool.accounting_warning", "tool.finished"],
        )
        self.assertEqual(events[-1].outcome, "succeeded")
        self.assertEqual(events[1].payload["phase"], "post_success")
        self.assertEqual(events[0].payload["call_id"], events[1].payload["call_id"])
        self.assertEqual(events[1].payload["call_id"], events[2].payload["call_id"])
        self.assertNotIn(error_secret, repr(events))
        self.assertNotIn("increment-once", repr(events))
        self.assertNotIn(error_secret.encode(), disk_bytes)
        self.assertNotIn(b"increment-once", disk_bytes)
        self.assertNotIn(error_secret, repr(logger.warning.call_args_list))
        self.assertNotIn("increment-once", repr(logger.warning.call_args_list))

    def test_rust_no_call_save_failure_restores_exact_accounting(self):
        calls = []
        logger = Mock()
        registry = SkillRegistry()
        skill = Skill(
            "rusty",
            "Rusty",
            "rusty | value",
            lambda argument: calls.append(argument) or "must-not-run",
        )
        skill.mastery = 0.7
        skill.rust_level = 0.9
        skill.last_used = 321.0
        registry.register(skill)
        accounting_before = (skill.mastery, skill.rust_level, skill.last_used)
        error_secret = "rust-storage-secret-m23"

        with TemporaryDirectory() as temp_dir:
            journal_root = Path(temp_dir) / "journal"
            journal = EventJournal(journal_root)
            with (
                journal_context(journal, self._context("accounting-rust")),
                patch("core.skills.random.random", return_value=0.0),
                patch("core.skills.time.time", return_value=654.0),
                patch.object(
                    registry,
                    "_save_unsafe",
                    side_effect=OSError(error_secret),
                ) as save,
                patch("core.logger.get_logger", return_value=logger),
            ):
                result = registry.execute("rusty", "do-not-execute")
            events = list(journal.iter_events())
            disk_bytes = b"".join(
                path.read_bytes()
                for path in journal_root.rglob("*")
                if path.is_file()
            )

        self.assertIn("tool was not executed", result)
        self.assertEqual(calls, [])
        self.assertEqual(
            (skill.mastery, skill.rust_level, skill.last_used),
            accounting_before,
        )
        save.assert_called_once_with()
        self.assertEqual(
            [event.event_type for event in events],
            ["tool.accounting_warning"],
        )
        self.assertEqual(events[0].payload["phase"], "rust_no_call")
        self.assertNotIn("call_id", events[0].payload)
        self.assertEqual(events[0].outcome, "failed")
        self.assertNotIn(error_secret, repr(events))
        self.assertNotIn("do-not-execute", repr(events))
        self.assertNotIn(error_secret.encode(), disk_bytes)
        self.assertNotIn(b"do-not-execute", disk_bytes)
        self.assertNotIn(error_secret, repr(logger.warning.call_args_list))
        self.assertNotIn("do-not-execute", repr(logger.warning.call_args_list))


if __name__ == "__main__":
    unittest.main()
