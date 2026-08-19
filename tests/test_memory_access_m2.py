import threading
import time
import unittest
from types import MappingProxyType, SimpleNamespace
from unittest.mock import patch

from config import Config
from core.engine.cognitive_engine import CognitiveEngine
from core.engine.interaction import InteractionController
from core.engine.interaction_actor import InteractionRequest
from core.memory_context import (
    DEFAULT_MEMORY_ACCESS_CONTEXT,
    MemoryAccessContext,
    MemoryScope,
    current_memory_context,
    interaction_memory_context,
    maintenance_memory_context,
    memory_context_scope,
)


class MemoryAccessContextM2Tests(unittest.TestCase):
    def test_default_context_is_single_owner_not_multi_user(self):
        self.assertEqual(current_memory_context(), DEFAULT_MEMORY_ACCESS_CONTEXT)
        self.assertEqual(
            DEFAULT_MEMORY_ACCESS_CONTEXT.read_scopes,
            (MemoryScope.AGENT, MemoryScope.OWNER),
        )
        self.assertEqual(
            DEFAULT_MEMORY_ACCESS_CONTEXT.write_scope,
            MemoryScope.OWNER,
        )

    def test_private_interaction_has_no_persistent_read_or_write_scope(self):
        context = interaction_memory_context(
            source="discord:user supplied text",
            request_id="private-request-id",
            private_ephemeral=True,
            local_only=True,
        )

        self.assertEqual(context.read_scopes, ())
        self.assertIsNone(context.write_scope)
        self.assertTrue(context.private_ephemeral)
        self.assertTrue(context.local_only)
        self.assertIsNone(context.source_event_id)
        self.assertNotIn(" ", context.origin_source)

    def test_backend_local_standard_request_keeps_owner_scope(self):
        context = interaction_memory_context(
            source="web",
            request_id="request-1",
            private_ephemeral=False,
            local_only=True,
        )

        self.assertFalse(context.private_ephemeral)
        self.assertTrue(context.local_only)
        self.assertEqual(context.write_scope, MemoryScope.OWNER)
        self.assertEqual(
            context.read_scopes,
            (MemoryScope.AGENT, MemoryScope.OWNER),
        )

    def test_nested_scope_restores_previous_context(self):
        maintenance = maintenance_memory_context(
            origin_kind="sleep",
            source_event_id="sleep-event-1",
        )
        interaction = interaction_memory_context(
            source="web",
            request_id="request-2",
            private_ephemeral=False,
            local_only=False,
        )

        with memory_context_scope(maintenance):
            self.assertEqual(current_memory_context(), maintenance)
            self.assertEqual(
                current_memory_context().source_event_id,
                "sleep-event-1",
            )
            with memory_context_scope(interaction):
                self.assertEqual(current_memory_context(), interaction)
            self.assertEqual(current_memory_context(), maintenance)
        self.assertEqual(current_memory_context(), DEFAULT_MEMORY_ACCESS_CONTEXT)

    def test_invalid_scope_is_rejected(self):
        with self.assertRaises(ValueError):
            MemoryAccessContext(read_scopes=("world",))
        with self.assertRaises(ValueError):
            MemoryAccessContext(
                read_scopes=(MemoryScope.OWNER,),
                write_scope=MemoryScope.AGENT,
            )

    def test_actor_request_binds_and_resets_interaction_context(self):
        captured = []

        def interaction_loop(*_args, **_kwargs):
            captured.append(current_memory_context())
            return "ok"

        engine = object.__new__(CognitiveEngine)
        engine.interaction = SimpleNamespace(interaction_loop=interaction_loop)
        engine.memory_ops = SimpleNamespace(sleep=lambda: None)
        request = InteractionRequest(
            request_id="request-3",
            payload=MappingProxyType({
                "user_input": "hello",
                "force_local": False,
                "private_ephemeral": False,
            }),
            source="web",
            cancel_event=threading.Event(),
            submitted_at=time.monotonic(),
        )

        self.assertEqual(engine._run_interaction_request(request), "ok")
        self.assertEqual(captured[0].origin_kind, "interaction")
        self.assertEqual(captured[0].origin_source, "web")
        self.assertEqual(captured[0].write_scope, MemoryScope.OWNER)
        self.assertEqual(current_memory_context(), DEFAULT_MEMORY_ACCESS_CONTEXT)

    def test_actor_private_request_never_exposes_a_correlation_id_to_memory(self):
        captured = []
        engine = object.__new__(CognitiveEngine)
        engine.interaction = SimpleNamespace(
            interaction_loop=lambda *_args, **_kwargs: captured.append(
                current_memory_context()
            )
        )
        engine.memory_ops = SimpleNamespace(sleep=lambda: None)
        request = InteractionRequest(
            request_id="private-secret-id",
            payload=MappingProxyType({
                "user_input": "/local secret",
                "force_local": True,
                "private_ephemeral": True,
            }),
            source="discord",
            cancel_event=threading.Event(),
            submitted_at=time.monotonic(),
        )

        engine._run_interaction_request(request)

        self.assertTrue(captured[0].private_ephemeral)
        self.assertEqual(captured[0].read_scopes, ())
        self.assertIsNone(captured[0].write_scope)
        self.assertIsNone(captured[0].source_event_id)
        self.assertEqual(current_memory_context(), DEFAULT_MEMORY_ACCESS_CONTEXT)

    def test_sleep_request_uses_maintenance_context_and_carries_event_id(self):
        captured = []
        engine = object.__new__(CognitiveEngine)
        engine.memory_ops = SimpleNamespace(
            sleep=lambda: captured.append(current_memory_context())
        )
        request = InteractionRequest(
            request_id="sleep-request-1",
            payload=MappingProxyType({"operation": "sleep"}),
            source="web",
            cancel_event=threading.Event(),
            submitted_at=time.monotonic(),
        )

        engine._run_interaction_request(request)

        self.assertEqual(captured[0].read_scopes, (
            MemoryScope.AGENT,
            MemoryScope.OWNER,
        ))
        self.assertIsNone(captured[0].write_scope)
        self.assertEqual(captured[0].origin_kind, "sleep")
        self.assertEqual(captured[0].origin_source, "web")
        self.assertEqual(captured[0].source_event_id, "sleep-request-1")
        self.assertEqual(current_memory_context(), DEFAULT_MEMORY_ACCESS_CONTEXT)

    def test_in_band_sleep_temporarily_drops_interaction_write_scope(self):
        captured = []
        engine = SimpleNamespace(
            memory_ops=SimpleNamespace(
                sleep=lambda: captured.append(current_memory_context())
            )
        )
        controller = object.__new__(InteractionController)
        controller.engine = engine
        interaction = interaction_memory_context(
            source="web",
            request_id="interaction-event-1",
            private_ephemeral=False,
            local_only=False,
        )

        with memory_context_scope(interaction):
            controller._run_sleep_maintenance()
            self.assertEqual(current_memory_context(), interaction)

        self.assertIsNone(captured[0].write_scope)
        self.assertEqual(captured[0].origin_kind, "sleep")
        self.assertEqual(captured[0].origin_source, "web")
        self.assertEqual(
            captured[0].source_event_id,
            "interaction-event-1",
        )

    def test_privacy_input_can_upgrade_but_never_downgrade_actual_local_input(self):
        class PendingFuture:
            def add_done_callback(self, callback):
                self.callback = callback

        class SubmissionActor:
            def submit(self, payload, *, source, request_id):
                request = InteractionRequest(
                    request_id=request_id,
                    payload=payload,
                    source=source,
                    cancel_event=threading.Event(),
                    submitted_at=time.monotonic(),
                )
                return SimpleNamespace(request=request, future=PendingFuture())

        class PinnedJournal:
            def append_pinned_safe(self, *_args, **_kwargs):
                return self, SimpleNamespace(event_id="a" * 32)

        captured = []

        def interaction_loop(*_args, **kwargs):
            captured.append((current_memory_context(), dict(kwargs)))
            return "ok"

        engine = object.__new__(CognitiveEngine)
        engine.interaction = SimpleNamespace(
            _requires_local_backend=InteractionController._requires_local_backend,
            _is_private_ephemeral_input=(
                InteractionController._is_private_ephemeral_input
            ),
            interaction_loop=interaction_loop,
        )
        engine.interaction_actor = SubmissionActor()
        engine.event_journal = PinnedJournal()
        engine._journal_tracking_lock = threading.Lock()
        engine._journal_requests = {}
        engine.memory_ops = SimpleNamespace(sleep=lambda: None)

        leaked_request_id = "must-not-be-a-private-correlation-id"
        with patch.object(Config, "USE_LOCAL_ONLY", False), patch.object(
            Config, "FORCE_LOCAL_COMMANDS", ["/local", "offline"]
        ):
            ticket = engine.submit_interaction(
                "/local actual secret",
                privacy_input="transport says public",
                source="discord",
                request_id=leaked_request_id,
            )

        payload = ticket.request.payload
        self.assertIsInstance(payload, MappingProxyType)
        self.assertTrue(payload["private_ephemeral"])
        self.assertTrue(payload["force_local"])

        journal_state = engine._journal_requests[id(ticket.request)]
        self.assertTrue(journal_state.context.private_ephemeral)
        self.assertNotEqual(journal_state.context.request_id, leaked_request_id)
        self.assertNotIn(leaked_request_id, repr(journal_state.context))

        self.assertEqual(engine._run_interaction_request(ticket.request), "ok")
        memory_context, handler_kwargs = captured[0]
        self.assertTrue(memory_context.private_ephemeral)
        self.assertTrue(memory_context.local_only)
        self.assertIsNone(memory_context.source_event_id)
        self.assertTrue(handler_kwargs["private_ephemeral"])
        self.assertTrue(handler_kwargs["force_local"])
        self.assertNotIn(leaked_request_id, repr(memory_context))
        self.assertEqual(current_memory_context(), DEFAULT_MEMORY_ACCESS_CONTEXT)


if __name__ == "__main__":
    unittest.main()
