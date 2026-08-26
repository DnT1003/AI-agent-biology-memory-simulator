import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from components.llm import LLM
from config import Config
from core.agent_state import AgentState, StateMachine
from core.event_journal import EventJournal, JournalContext, journal_context
from core.local_llm import LocalInferenceJSONError, LocalLLM
from core.skills import Skill, SkillRegistry


class _Settings:
    def __init__(self, **values):
        self.values = values

    def get(self, key, default=None):
        return self.values.get(key, default)


def _llm(provider="gemini", **settings):
    instance = LLM.__new__(LLM)
    instance.settings = _Settings(provider=provider, **settings)
    instance.local_llm = Mock()
    instance.ego = None
    instance.client = None
    return instance


class JournalHookM1Tests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "journal"
        self.journal = EventJournal(self.root)
        self.context = JournalContext(
            correlation_id="hook-request",
            trace_id="hook-request",
            request_id="hook-request",
            source="test",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def events(self):
        return list(self.journal.iter_events())

    def disk_bytes(self):
        return b"".join(
            path.read_bytes() for path in self.root.rglob("*") if path.is_file()
        )

    def test_text_inference_records_metadata_only_success(self):
        prompt_secret = "PROMPT-SECRET-m1-41"
        output_secret = "OUTPUT-SECRET-m1-52"
        llm = _llm("gemini", gemini_model="safe-model")

        with (
            journal_context(self.journal, self.context),
            patch("core.local_llm._model_status", "unavailable"),
            patch.object(
                llm,
                "_generate_text_with_retry",
                return_value=(output_secret, 0.0),
            ) as generate,
        ):
            self.assertEqual((output_secret, 0.0), llm.generate_text(prompt_secret))

        events = self.events()
        self.assertEqual(
            [event.event_type for event in events],
            ["inference.started", "inference.finished"],
        )
        self.assertEqual(events[0].payload["call_id"], events[1].payload["call_id"])
        self.assertEqual(events[0].payload["kind"], "text")
        self.assertEqual(events[1].payload["backend"], "cloud")
        self.assertEqual(events[1].outcome, "succeeded")
        self.assertEqual(generate.call_count, 1)
        on_disk = self.disk_bytes()
        self.assertNotIn(prompt_secret.encode(), on_disk)
        self.assertNotIn(output_secret.encode(), on_disk)

    def test_json_inference_failure_records_error_class_not_message(self):
        prompt_secret = "JSON-PROMPT-SECRET-m1-63"
        error_secret = "ERROR-MESSAGE-SECRET-m1-74"
        llm = _llm("gemini", gemini_model="safe-model")

        with (
            journal_context(self.journal, self.context),
            patch("core.local_llm._model_status", "unavailable"),
            patch.object(
                llm,
                "_generate_json_with_retry",
                side_effect=RuntimeError(error_secret),
            ),
            patch.object(Config, "USE_HYBRID", False),
            patch("components.llm.logger.error") as error_log,
            self.assertRaisesRegex(RuntimeError, error_secret),
        ):
            llm.generate_json(prompt_secret)

        events = self.events()
        self.assertEqual(len(events), 2)
        self.assertEqual(events[-1].outcome, "failed")
        self.assertEqual(events[-1].payload["error_type"], "RuntimeError")
        on_disk = self.disk_bytes()
        self.assertNotIn(prompt_secret.encode(), on_disk)
        self.assertNotIn(error_secret.encode(), on_disk)
        self.assertNotIn(error_secret, repr(error_log.call_args_list))
        self.assertIn("RuntimeError", repr(error_log.call_args_list))

    def test_force_local_failure_never_logs_private_exception_message(self):
        prompt_secret = "PRIVATE-LOCAL-PROMPT-m1-logging"
        error_secret = "PRIVATE-LOCAL-ERROR-m1-logging"
        llm = _llm("gemini", gemini_model="safe-model")

        with (
            journal_context(self.journal, self.context),
            patch("core.local_llm._model_status", "ready"),
            patch.object(
                llm,
                "_generate_json_with_retry",
                side_effect=LocalInferenceJSONError(error_secret),
            ),
            patch("components.llm.logger.error") as error_log,
            self.assertRaisesRegex(LocalInferenceJSONError, error_secret),
        ):
            llm.generate_json(prompt_secret, force_local=True)

        self.assertNotIn(prompt_secret, repr(error_log.call_args_list))
        self.assertNotIn(error_secret, repr(error_log.call_args_list))
        self.assertIn("LocalInferenceJSONError", repr(error_log.call_args_list))

    def test_tool_records_one_pair_without_args_result_or_error_message(self):
        argument_secret = "TOOL-ARG-SECRET-m1-85"
        result_secret = "TOOL-RESULT-SECRET-m1-96"
        error_secret = "TOOL-ERROR-SECRET-m1-07"
        registry = SkillRegistry()
        registry.register(Skill("safe_tool", "safe", "safe_tool", lambda _: result_secret))
        registry.register(
            Skill(
                "broken_tool",
                "safe",
                "broken_tool",
                lambda _: (_ for _ in ()).throw(ValueError(error_secret)),
            )
        )

        with (
            journal_context(self.journal, self.context),
            patch.object(registry, "_save_unsafe"),
        ):
            self.assertEqual(result_secret, registry.execute("safe_tool", argument_secret))
            failure = registry.execute("broken_tool", argument_secret)

        self.assertIn(error_secret, failure)
        events = self.events()
        self.assertEqual(
            [event.event_type for event in events],
            ["tool.started", "tool.finished", "tool.started", "tool.finished"],
        )
        self.assertEqual(events[1].outcome, "succeeded")
        self.assertEqual(events[3].outcome, "failed")
        self.assertEqual(events[3].payload["error_type"], "ValueError")
        self.assertEqual(events[0].payload["call_id"], events[1].payload["call_id"])
        self.assertEqual(events[2].payload["call_id"], events[3].payload["call_id"])
        on_disk = self.disk_bytes()
        for secret in (argument_secret, result_secret, error_secret):
            self.assertNotIn(secret.encode(), on_disk)

    def test_state_change_is_recorded_only_after_releasing_state_lock(self):
        machine = StateMachine()
        lock_was_free = []

        def observe(*args, **kwargs):
            acquired = machine._lock.acquire(blocking=False)
            lock_was_free.append(acquired)
            if acquired:
                machine._lock.release()

        with patch("core.agent_state.record_current_event", side_effect=observe) as record:
            self.assertTrue(machine.transition(AgentState.THINKING))
            machine.force(AgentState.IDLE)

        self.assertEqual(lock_was_free, [True, True])
        self.assertEqual(record.call_count, 2)
        self.assertEqual(record.call_args_list[0].args[1]["from_state"], "IDLE")
        self.assertEqual(record.call_args_list[0].args[1]["to_state"], "THINKING")
        self.assertFalse(record.call_args_list[0].args[1]["forced"])
        self.assertTrue(record.call_args_list[1].args[1]["forced"])

    def test_private_scope_discards_all_hook_payloads(self):
        private = JournalContext(
            correlation_id="private-hook",
            trace_id="private-hook",
            request_id="private-hook",
            source="test",
            private_ephemeral=True,
        )
        llm = _llm("gemini", gemini_model="private-model-sentinel")

        with (
            journal_context(self.journal, private),
            patch("core.local_llm._model_status", "unavailable"),
            patch.object(llm, "_generate_text_with_retry", return_value=("private-output", 0.0)),
        ):
            llm.generate_text("private-prompt")

        events = self.events()
        self.assertEqual(len(events), 2)
        self.assertTrue(all(event.payload == {} for event in events))
        on_disk = self.disk_bytes()
        for secret in ("private-model-sentinel", "private-output", "private-prompt"):
            self.assertNotIn(secret.encode(), on_disk)

    def test_invalid_local_json_never_logs_raw_model_output(self):
        secret = "PRIVATE-LOCAL-OUTPUT-SENTINEL-m1"
        local = LocalLLM.__new__(LocalLLM)
        local._build_prompt = Mock(return_value="safe-placeholder")
        local._infer = Mock(return_value=f"not-json {secret}")

        with (
            patch("core.local_llm.logger.warning") as warning,
            self.assertRaises(LocalInferenceJSONError),
        ):
            local.generate_json("private input")

        self.assertEqual(warning.call_count, 3)
        self.assertNotIn(secret, repr(warning.call_args_list))


if __name__ == "__main__":
    unittest.main()
