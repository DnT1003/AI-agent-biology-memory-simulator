import asyncio
import time
import unittest
import warnings
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

warnings.filterwarnings(
    "ignore",
    message=r"Using `httpx` with `starlette\.testclient` is deprecated.*",
)

from fastapi.testclient import TestClient

from core.chat_spool import ChatSpool
from core.engine.autonomous import AutonomousController
from core.engine.interaction_actor import (
    InteractionActorClosed,
    InteractionCancelled,
    InteractionQueueFull,
)
from dashboard import server as dashboard_server


class _FakeTicket:
    def __init__(self, *, result=None, error=None):
        self._result = result
        self._error = error

    async def wait(self):
        if self._error is not None:
            raise self._error
        return self._result


class _FakeClock:
    def __init__(self, now_ns=1_000_000_000):
        self.now_ns = now_ns

    def __call__(self):
        return self.now_ns

    def advance(self, seconds):
        self.now_ns += int(seconds * 1_000_000_000)


class _FakeEngine:
    def __init__(self, mode):
        self.mode = mode
        self.calls = []
        self.last_interaction_time = 0.0

    def submit_interaction(self, message, **kwargs):
        self.calls.append((message, kwargs))
        request_id = kwargs["request_id"]
        if self.mode == "full":
            raise InteractionQueueFull(1)
        if self.mode == "closed":
            raise InteractionActorClosed()
        if self.mode == "cancelled":
            return _FakeTicket(error=InteractionCancelled(request_id, "test cancellation"))
        if self.mode == "failure":
            return _FakeTicket(error=RuntimeError("test handler failure"))
        if self.mode == "oversized":
            return _FakeTicket(result={"response": "x" * 1_000})
        return _FakeTicket(result={"response": f"reply to {message}"})


class DashboardChatTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "chat_spool"
        self.requests = ChatSpool(
            self.root,
            "request",
            max_payload_bytes=8,
            max_count=1,
            lease_seconds=60,
        )
        self.responses = ChatSpool(
            self.root,
            "response",
            max_payload_bytes=64,
            max_count=4,
            lease_seconds=60,
        )
        self.spool_patch = patch.object(
            dashboard_server,
            "_get_chat_spools",
            return_value=(self.requests, self.responses),
        )
        self.spool_patch.start()
        self.client = TestClient(dashboard_server.app)

    def tearDown(self):
        self.spool_patch.stop()
        self.temp_dir.cleanup()

    def test_post_chat_returns_202_and_persists_a_durable_request(self):
        response = self.client.post("/api/chat", json={"message": " hello "})

        self.assertEqual(response.status_code, 202)
        body = response.json()
        self.assertEqual(body["status"], "queued")
        self.assertRegex(body["id"], r"^[0-9]{20}-[0-9a-f]{32}$")
        self.assertEqual(self.requests.stats()["pending"], 1)

        claim = self.requests.claim()[0]
        self.assertEqual(claim.envelope.id, body["id"])
        self.assertEqual(claim.envelope.content, "hello")

    def test_response_get_claims_once_then_ack_completes_idempotently(self):
        request_id = self.requests.enqueue_request("hello").message_id
        self.responses.publish_response(request_id, "durable reply")

        first = self.client.get("/api/chat", params={"id": request_id})
        self.assertEqual(first.status_code, 200)
        messages = first.json()["messages"]
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["id"], request_id)
        self.assertEqual(messages[0]["content"], "durable reply")
        self.assertRegex(
            messages[0]["receipt"],
            rf"^{request_id}\.[0-9]{{20}}\.[0-9a-f]{{32}}$",
        )

        # The lease has not elapsed, so a second poll cannot double-deliver it.
        second = self.client.get("/api/chat", params={"id": request_id})
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json(), {"messages": [], "terminal": []})

        receipt = messages[0]["receipt"]
        ack = self.client.post("/api/chat/ack", json={"receipts": [receipt]})
        self.assertEqual(ack.status_code, 200)
        self.assertEqual(ack.json(), {"acked": [receipt], "missing": 0})
        self.assertEqual(self.responses.stats()["processing"], 0)

        # ACK leaves a bounded completion tombstone. Publishing the same
        # request id again remains idempotent after browser delivery.
        self.assertTrue(self.responses.contains(request_id))
        self.assertFalse(
            self.responses.publish_response(request_id, "duplicate reply").created
        )
        self.assertEqual(
            self.client.get("/api/chat", params={"id": request_id}).json(),
            {
                "messages": [],
                "terminal": [{"id": request_id, "state": "completed"}],
            },
        )

    def test_response_claim_is_correlated_to_requesting_tab_ids(self):
        first_id = self.requests.enqueue_request("first").message_id
        first_claim = self.requests.claim()[0]
        self.assertTrue(self.requests.ack(first_claim.receipt))
        second_id = self.requests.enqueue_request("second").message_id
        self.responses.publish_response(first_id, "first reply")
        self.responses.publish_response(second_id, "second reply")

        first_tab = self.client.get("/api/chat", params={"id": first_id})
        self.assertEqual(
            [message["id"] for message in first_tab.json()["messages"]],
            [first_id],
        )
        self.assertEqual(self.responses.stats()["pending"], 1)

        second_tab = self.client.get("/api/chat", params={"id": second_id})
        self.assertEqual(
            [message["id"] for message in second_tab.json()["messages"]],
            [second_id],
        )

    def test_chat_api_maps_empty_oversized_full_and_traversal_errors(self):
        empty = self.client.post("/api/chat", json={"message": "   "})
        oversized = self.client.post("/api/chat", json={"message": "123456789"})
        accepted = self.client.post("/api/chat", json={"message": "first"})
        full = self.client.post("/api/chat", json={"message": "second"})
        traversal = self.client.post(
            "/api/chat/ack", json={"receipts": ["../../responses/pending"]}
        )

        self.assertEqual(empty.status_code, 400)
        self.assertEqual(oversized.status_code, 413)
        self.assertEqual(accepted.status_code, 202)
        self.assertEqual(full.status_code, 429)
        self.assertEqual(traversal.status_code, 400)

    def test_private_local_command_is_rejected_before_durable_write(self):
        sentinel = "SECRET_SENTINEL"

        response = self.client.post(
            "/api/chat", json={"message": f"/local {sentinel}"}
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.requests.stats()["pending"], 0)
        durable_bytes = b"".join(
            path.read_bytes() for path in self.root.rglob("*.json")
        )
        self.assertNotIn(sentinel.encode("utf-8"), durable_bytes)

    def test_dead_request_without_response_is_reported_terminal(self):
        request_id = self.requests.enqueue_request("fail").message_id
        claim = self.requests.claim()[0]
        self.assertTrue(self.requests.dead_letter(claim.receipt, "handler_error"))

        result = self.client.get("/api/chat", params={"id": request_id})

        self.assertEqual(
            result.json(),
            {
                "messages": [],
                "terminal": [{"id": request_id, "state": "failed"}],
            },
        )

    def test_response_snapshot_wins_publish_before_request_ack_race(self):
        message_id = f"{time.time_ns():020d}-{'a' * 32}"
        response_visible = False
        requests = Mock()
        responses = Mock()
        responses.claim.return_value = []
        responses.retention_expired.return_value = True

        def request_state(_message_id):
            nonlocal response_visible
            response_visible = True
            return None

        requests.message_state.side_effect = request_state
        responses.message_state.side_effect = (
            lambda _message_id: "pending" if response_visible else None
        )

        with patch.object(
            dashboard_server,
            "_get_chat_spools",
            return_value=(requests, responses),
        ):
            result = self.client.get("/api/chat", params={"id": message_id})

        self.assertEqual(result.json(), {"messages": [], "terminal": []})
        requests.message_state.assert_called_once_with(message_id)
        responses.message_state.assert_called_once_with(message_id)

    def test_dashboard_ui_rotates_poll_ids_and_removes_only_acked_receipts(self):
        html = dashboard_server.DASHBOARD_FILE.read_text(encoding="utf-8")

        self.assertIn("pendingChatIds.delete(id);", html)
        self.assertIn("pendingChatIds.add(id);", html)
        self.assertIn("ackedReceipts.has(item.receipt)", html)
        self.assertIn("data.terminal", html)


class AutonomousChatTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.base_root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _spools(self, name):
        root = self.base_root / name
        return (
            ChatSpool(root, "request", lease_seconds=60),
            ChatSpool(root, "response", lease_seconds=60),
        )

    @staticmethod
    def _controller(engine, spools):
        controller = AutonomousController(engine)
        controller._chat_spools = spools
        # Keep this unit focused on the claim/handler/finalization protocol.
        controller._last_chat_recovery = time.monotonic()
        return controller

    def test_success_publishes_response_before_request_ack(self):
        requests, responses = self._spools("success")
        queued = requests.enqueue_request("question")
        engine = _FakeEngine("success")
        controller = self._controller(engine, (requests, responses))
        order = []
        publish_response = responses.publish_response
        ack_request = requests.ack

        def record_publish(*args, **kwargs):
            order.append("publish")
            return publish_response(*args, **kwargs)

        def record_ack(*args, **kwargs):
            order.append("ack")
            return ack_request(*args, **kwargs)

        with patch.object(responses, "publish_response", side_effect=record_publish), patch.object(
            requests, "ack", side_effect=record_ack
        ):
            handled = asyncio.run(controller._process_web_chat_once())

        self.assertTrue(handled)
        self.assertEqual(order, ["publish", "ack"])
        self.assertEqual(requests.stats(), {"pending": 0, "processing": 0, "dead": 0})
        response_claim = responses.claim()[0]
        self.assertEqual(response_claim.envelope.id, queued.message_id)
        self.assertEqual(response_claim.envelope.content, "reply to question")
        self.assertEqual(engine.calls[0][1]["source"], "web")
        self.assertEqual(engine.calls[0][1]["request_id"], queued.message_id)

    def test_actor_full_or_closed_releases_unexecuted_request(self):
        for mode in ("full", "closed"):
            with self.subTest(mode=mode):
                requests, responses = self._spools(f"admission-{mode}")
                queued = requests.enqueue_request(f"{mode} request")
                engine = _FakeEngine(mode)
                controller = self._controller(engine, (requests, responses))

                handled = asyncio.run(controller._process_web_chat_once())

                self.assertFalse(handled)
                self.assertEqual(
                    requests.stats(), {"pending": 1, "processing": 0, "dead": 0}
                )
                self.assertTrue(requests.contains(queued.message_id))
                self.assertEqual(
                    responses.stats(), {"pending": 0, "processing": 0, "dead": 0}
                )

    def test_handler_failure_or_cancellation_goes_to_dlq_without_replay(self):
        for mode, reason in (("failure", "handler_error"), ("cancelled", "cancelled")):
            with self.subTest(mode=mode):
                requests, responses = self._spools(f"terminal-{mode}")
                queued = requests.enqueue_request(f"{mode} request")
                engine = _FakeEngine(mode)
                controller = self._controller(engine, (requests, responses))

                handled = asyncio.run(controller._process_web_chat_once())

                self.assertTrue(handled)
                self.assertEqual(
                    requests.stats(), {"pending": 0, "processing": 0, "dead": 1}
                )
                dead_files = list(requests.dead_dir.glob("*.json"))
                self.assertEqual(len(dead_files), 1)
                self.assertIn(queued.message_id, dead_files[0].name)
                self.assertTrue(dead_files[0].name.endswith(f".{reason}.json"))
                self.assertEqual(
                    responses.stats(), {"pending": 1, "processing": 0, "dead": 0}
                )
                terminal = responses.claim()[0]
                self.assertEqual(terminal.envelope.id, queued.message_id)
                self.assertTrue(terminal.envelope.content.strip())
                self.assertTrue(responses.ack(terminal.receipt))

                # DLQ is terminal: another poll cannot submit the same request.
                replayed = asyncio.run(controller._process_web_chat_once())
                self.assertFalse(replayed)
                self.assertEqual(len(engine.calls), 1)

    def test_full_response_queue_backpressures_before_handler_execution(self):
        root = self.base_root / "response-backpressure"
        requests = ChatSpool(root, "request", lease_seconds=60)
        responses = ChatSpool(
            root, "response", max_count=1, lease_seconds=60
        )
        id_source = ChatSpool(
            self.base_root / "id-source", "request", lease_seconds=60
        )
        blocker_id = id_source.enqueue_request("blocker").message_id
        responses.publish_response(blocker_id, "not delivered yet")
        queued = requests.enqueue_request("must wait")
        engine = _FakeEngine("success")
        controller = self._controller(engine, (requests, responses))

        self.assertFalse(asyncio.run(controller._process_web_chat_once()))
        self.assertEqual(engine.calls, [])
        self.assertEqual(
            requests.stats(), {"pending": 1, "processing": 0, "dead": 0}
        )

        blocker = responses.claim()[0]
        self.assertTrue(responses.ack(blocker.receipt))
        self.assertTrue(asyncio.run(controller._process_web_chat_once()))
        self.assertEqual(len(engine.calls), 1)
        delivered = responses.claim()[0]
        self.assertEqual(delivered.envelope.id, queued.message_id)
        self.assertEqual(delivered.envelope.content, "reply to must wait")

    def test_abandoned_response_expires_before_backpressure_blocks_handler(self):
        clock = _FakeClock()
        root = self.base_root / "response-retention"
        requests = ChatSpool(root, "request", clock_ns=clock)
        responses = ChatSpool(
            root,
            "response",
            max_count=1,
            max_dead_count=2,
            retention_seconds=10,
            clock_ns=clock,
        )
        id_source = ChatSpool(
            self.base_root / "retention-id-source", "request", clock_ns=clock
        )
        blocker_id = id_source.enqueue_request("abandoned tab").message_id
        responses.publish_response(blocker_id, "never acknowledged")
        clock.advance(11)
        queued = requests.enqueue_request("must make progress")
        engine = _FakeEngine("success")
        controller = self._controller(engine, (requests, responses))

        self.assertTrue(asyncio.run(controller._process_web_chat_once()))

        self.assertEqual(len(engine.calls), 1)
        self.assertEqual(responses.message_state(blocker_id), "dead")
        delivered = responses.claim()[0]
        self.assertEqual(delivered.envelope.id, queued.message_id)

    def test_oversized_result_gets_durable_terminal_response(self):
        root = self.base_root / "oversized-result"
        requests = ChatSpool(root, "request", lease_seconds=60)
        responses = ChatSpool(
            root,
            "response",
            max_payload_bytes=64,
            lease_seconds=60,
        )
        queued = requests.enqueue_request("large answer")
        engine = _FakeEngine("oversized")
        controller = self._controller(engine, (requests, responses))

        self.assertTrue(asyncio.run(controller._process_web_chat_once()))
        self.assertEqual(
            requests.stats(), {"pending": 0, "processing": 0, "dead": 1}
        )
        terminal = responses.claim()[0]
        self.assertEqual(terminal.envelope.id, queued.message_id)
        self.assertIn("exceeded", terminal.envelope.content)

    def test_publish_failure_never_false_terminalizes_executed_request(self):
        requests, responses = self._spools("publish-failure")
        requests.enqueue_request("side effect already happened")
        engine = _FakeEngine("success")
        controller = self._controller(engine, (requests, responses))

        with patch.object(
            responses,
            "_commit_temp",
            side_effect=OSError("disk unavailable"),
        ):
            self.assertTrue(asyncio.run(controller._process_web_chat_once()))

        self.assertEqual(len(engine.calls), 1)
        self.assertEqual(
            requests.stats(), {"pending": 0, "processing": 1, "dead": 0}
        )
        self.assertEqual(
            responses.stats(), {"pending": 0, "processing": 0, "dead": 0}
        )

        # Once storage recovers, the controller publishes the saved result and
        # ACKs without invoking the side-effecting handler a second time.
        self.assertTrue(asyncio.run(controller._process_web_chat_once()))
        self.assertEqual(len(engine.calls), 1)
        self.assertEqual(
            requests.stats(), {"pending": 0, "processing": 0, "dead": 0}
        )
        recovered = responses.claim()[0]
        self.assertEqual(
            recovered.envelope.content, "reply to side effect already happened"
        )


if __name__ == "__main__":
    unittest.main()
