import json
import multiprocessing
import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from core.chat_spool import (
    ChatSpool,
    ChatSpoolIOError,
    InvalidReceipt,
    PayloadTooLarge,
    QueueFull,
)


class FakeClock:
    def __init__(self, now_ns=1_000_000_000):
        self.now_ns = now_ns
        self.lock = threading.Lock()

    def __call__(self):
        with self.lock:
            return self.now_ns

    def advance(self, seconds):
        with self.lock:
            self.now_ns += int(seconds * 1_000_000_000)


def _process_enqueue_worker(root, count, max_count, result_queue):
    """Top-level target so the concurrency test works with Windows spawn."""
    try:
        spool = ChatSpool(root, "request", max_count=max_count)
        created = []
        full = 0
        for index in range(count):
            try:
                result = spool.enqueue_request(f"process-message-{os.getpid()}-{index}")
                created.append(result.message_id)
            except QueueFull:
                full += 1
        result_queue.put(("ok", created, full))
    except Exception as exc:  # pragma: no cover - reported in the parent process
        result_queue.put(("error", repr(exc), 0))


class ChatSpoolTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "chat_spool"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_atomic_publish_leaves_no_partial_json_and_envelope_is_immutable(self):
        spool = ChatSpool(self.root, "request")

        with patch.object(spool, "_commit_temp", side_effect=OSError("simulated crash")):
            with self.assertRaises(ChatSpoolIOError):
                spool.enqueue_request("not visible")

        self.assertEqual(spool.stats(), {"pending": 0, "processing": 0, "dead": 0})
        self.assertEqual(list(spool.pending_dir.glob(".tmp-*")), [])

        result = spool.enqueue_request("durable content")
        pending = spool.pending_dir / f"{result.message_id}.json"
        before_claim = pending.read_bytes()
        self.assertEqual(json.loads(before_claim)["content"], "durable content")

        claim = spool.claim()[0]
        processing = spool.processing_dir / f"{claim.receipt}.json"
        self.assertEqual(processing.read_bytes(), before_claim)

    def test_transient_claim_read_error_is_typed_and_not_quarantined(self):
        spool = ChatSpool(self.root, "request")
        published = spool.enqueue_request("keep after transient read failure")

        with patch.object(Path, "read_bytes", side_effect=OSError("temporary EIO")):
            with self.assertRaises(ChatSpoolIOError):
                spool.claim()

        self.assertEqual(
            spool.stats(), {"pending": 0, "processing": 1, "dead": 0}
        )
        self.assertEqual(spool.message_state(published.message_id), "processing")

    def test_payload_and_active_count_are_bounded(self):
        spool = ChatSpool(self.root, "request", max_payload_bytes=8, max_count=2)

        first = spool.enqueue_request("one")
        spool.enqueue_request("two")
        claim = spool.claim(limit=1)[0]

        # Processing claims still consume an active queue slot.
        with self.assertRaises(QueueFull):
            spool.enqueue_request("three")
        with self.assertRaises(PayloadTooLarge):
            spool.enqueue_request("é" * 5)

        self.assertTrue(spool.ack(claim.receipt))
        replacement = spool.enqueue_request("three")
        self.assertNotEqual(first.message_id, replacement.message_id)
        self.assertEqual(spool.stats()["pending"], 2)

    def test_concurrent_thread_producers_and_claimers_do_not_duplicate(self):
        producer_a = ChatSpool(self.root, "request", max_count=80)
        producer_b = ChatSpool(self.root, "request", max_count=80)

        def publish(index):
            spool = producer_a if index % 2 else producer_b
            return spool.enqueue_request(f"message-{index}").message_id

        with ThreadPoolExecutor(max_workers=12) as executor:
            published = list(executor.map(publish, range(80)))

        self.assertEqual(len(set(published)), 80)
        self.assertEqual(producer_a.stats()["pending"], 80)

        consumer_a = ChatSpool(self.root, "request", max_count=80)
        consumer_b = ChatSpool(self.root, "request", max_count=80)
        with ThreadPoolExecutor(max_workers=2) as executor:
            batches = list(executor.map(lambda spool: spool.claim(80), (consumer_a, consumer_b)))

        claims = batches[0] + batches[1]
        claimed_ids = [claim.envelope.id for claim in claims]
        self.assertEqual(len(claimed_ids), 80)
        self.assertEqual(len(set(claimed_ids)), 80)
        self.assertEqual(set(claimed_ids), set(published))
        self.assertEqual(consumer_a.stats()["processing"], 80)

    def test_cross_process_capacity_and_unique_ids(self):
        process_count = 4
        messages_per_process = 10
        hard_capacity = 25
        context = multiprocessing.get_context("spawn")
        result_queue = context.Queue()
        processes = [
            context.Process(
                target=_process_enqueue_worker,
                args=(str(self.root), messages_per_process, hard_capacity, result_queue),
            )
            for _ in range(process_count)
        ]

        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=30)
            self.assertFalse(process.is_alive(), "chat spool worker did not terminate")
            self.assertEqual(process.exitcode, 0)

        created = []
        full = 0
        for _ in processes:
            status, value, worker_full = result_queue.get(timeout=5)
            self.assertEqual(status, "ok", value)
            created.extend(value)
            full += worker_full
        result_queue.close()

        self.assertEqual(len(created), hard_capacity)
        self.assertEqual(len(set(created)), hard_capacity)
        self.assertEqual(full, process_count * messages_per_process - hard_capacity)
        self.assertEqual(
            ChatSpool(self.root, "request", max_count=hard_capacity).stats()["pending"],
            hard_capacity,
        )

    def test_receipts_are_validated_and_path_contained(self):
        spool = ChatSpool(self.root, "request")
        spool.enqueue_request("hello")
        claim = spool.claim()[0]

        for malicious in (
            "../../settings",
            "..\\..\\settings",
            f"{claim.receipt}/../other",
            "not-a-receipt",
        ):
            with self.assertRaises(InvalidReceipt):
                spool.ack(malicious)

        with self.assertRaises(InvalidReceipt):
            spool.dead_letter(claim.receipt, "../escape")
        self.assertTrue(spool.ack(claim.receipt))
        self.assertFalse(spool.ack(claim.receipt))

    def test_stale_request_is_acked_with_response_otherwise_dead_lettered(self):
        clock = FakeClock()
        requests = ChatSpool(
            self.root, "request", lease_seconds=1, clock_ns=clock
        )
        responses = ChatSpool(
            self.root, "response", lease_seconds=1, clock_ns=clock
        )

        missing = requests.enqueue_request("will not be replayed")
        missing_claim = requests.claim()[0]
        self.assertEqual(missing_claim.envelope.id, missing.message_id)
        clock.advance(2)

        report = requests.recover_stale(responses)
        self.assertEqual(report.dead_requests, 1)
        self.assertEqual(report.acknowledged_requests, 0)
        self.assertEqual(requests.stats(), {"pending": 0, "processing": 0, "dead": 1})

        completed = requests.enqueue_request("response became durable")
        requests.claim()
        responses.publish_response(completed.message_id, "done")
        clock.advance(2)

        report = requests.recover_stale(responses)
        self.assertEqual(report.acknowledged_requests, 1)
        self.assertEqual(report.dead_requests, 0)
        self.assertEqual(requests.stats()["processing"], 0)
        self.assertTrue(responses.contains(completed.message_id))

    def test_stale_response_requeues_same_immutable_envelope(self):
        clock = FakeClock()
        responses = ChatSpool(
            self.root, "response", lease_seconds=1, clock_ns=clock
        )
        request_id = f"{clock():020d}-{'a' * 32}"
        responses.publish_response(request_id, "reply")
        first_claim = responses.claim()[0]
        processing = responses.processing_dir / f"{first_claim.receipt}.json"
        original_bytes = processing.read_bytes()
        clock.advance(2)

        report = responses.recover_stale()
        self.assertEqual(report.requeued_responses, 1)
        pending = responses.pending_dir / f"{request_id}.json"
        self.assertEqual(pending.read_bytes(), original_bytes)

        second_claim = responses.claim()[0]
        self.assertEqual(second_claim.envelope.id, request_id)
        self.assertNotEqual(second_claim.receipt, first_claim.receipt)

    def test_response_publish_is_idempotent_by_request_id(self):
        requests = ChatSpool(self.root, "request")
        responses = ChatSpool(self.root, "response", max_count=1)
        request_id = requests.enqueue_request("question").message_id

        with ThreadPoolExecutor(max_workers=12) as executor:
            results = list(
                executor.map(
                    lambda _: responses.publish_response(request_id, "same reply"),
                    range(30),
                )
            )

        self.assertEqual(sum(result.created for result in results), 1)
        self.assertEqual(responses.stats()["pending"], 1)
        claim = responses.claim()[0]
        self.assertEqual(claim.envelope.id, request_id)
        self.assertEqual(claim.envelope.reply_to, request_id)
        self.assertEqual(claim.envelope.content, "same reply")

        # Processing, completed and dead-letter states suppress republishing.
        self.assertFalse(responses.publish_response(request_id, "duplicate").created)
        self.assertTrue(responses.ack(claim.receipt))
        self.assertFalse(responses.publish_response(request_id, "duplicate").created)

        second_request_id = requests.enqueue_request("second question").message_id
        second_claim_result = responses.publish_response(second_request_id, "reply")
        self.assertTrue(second_claim_result.created)
        second_claim = responses.claim()[0]
        self.assertTrue(responses.dead_letter(second_claim.receipt, "delivery_failed"))
        self.assertFalse(responses.publish_response(second_request_id, "duplicate").created)

    def test_full_response_queue_stages_result_without_reexecuting_request(self):
        requests = ChatSpool(self.root, "request")
        responses = ChatSpool(self.root, "response", max_count=1)
        first_id = requests.enqueue_request("first").message_id
        second_id = requests.enqueue_request("second").message_id

        responses.publish_response(first_id, "first reply")
        self.assertFalse(responses.has_capacity())
        with self.assertRaises(QueueFull):
            responses.publish_response(second_id, "second reply")

        staged = responses.publish_response(
            second_id, "second reply", stage_if_full=True
        )
        self.assertTrue(staged.created)
        self.assertTrue(responses.contains(second_id))
        self.assertEqual(responses.promote_staged(), 0)

        first_claim = responses.claim()[0]
        self.assertTrue(responses.ack(first_claim.receipt))
        self.assertTrue(responses.has_capacity())
        self.assertEqual(responses.promote_staged(), 1)
        second_claim = responses.claim()[0]
        self.assertEqual(second_claim.envelope.id, second_id)
        self.assertEqual(second_claim.envelope.content, "second reply")

    def test_abandoned_pending_and_staged_responses_expire_and_free_capacity(self):
        clock = FakeClock()
        requests = ChatSpool(self.root, "request", clock_ns=clock)
        responses = ChatSpool(
            self.root,
            "response",
            max_count=1,
            max_dead_count=4,
            retention_seconds=10,
            clock_ns=clock,
        )
        first_id = requests.enqueue_request("first").message_id
        clock.advance(1)
        second_id = requests.enqueue_request("second").message_id
        responses.publish_response(first_id, "first reply")
        responses.publish_response(second_id, "second reply", stage_if_full=True)
        self.assertEqual(responses.stats()["pending"], 2)
        self.assertFalse(responses.has_capacity())

        clock.advance(11)
        self.assertEqual(responses.expire_stale_deliveries(), 2)

        self.assertEqual(
            responses.stats(), {"pending": 0, "processing": 0, "dead": 2}
        )
        self.assertEqual(responses.message_state(first_id), "dead")
        self.assertEqual(responses.message_state(second_id), "dead")
        self.assertTrue(responses.has_capacity())

    def test_claim_never_delivers_a_response_that_expired_before_claim(self):
        clock = FakeClock()
        requests = ChatSpool(self.root, "request", clock_ns=clock)
        responses = ChatSpool(
            self.root,
            "response",
            retention_seconds=10,
            clock_ns=clock,
        )
        request_id = requests.enqueue_request("question").message_id
        responses.publish_response(request_id, "reply")
        clock.advance(11)

        self.assertEqual(responses.claim(), [])
        self.assertEqual(responses.message_state(request_id), "dead")

    def test_unexecuted_claim_can_be_released_after_backpressure(self):
        spool = ChatSpool(self.root, "request")
        published = spool.enqueue_request("try again after admission")
        claim = spool.claim()[0]
        processing = spool.processing_dir / f"{claim.receipt}.json"
        original = processing.read_bytes()

        self.assertTrue(spool.release(claim.receipt))
        pending = spool.pending_dir / f"{published.message_id}.json"
        self.assertEqual(pending.read_bytes(), original)
        self.assertFalse(spool.release(claim.receipt))

        second_claim = spool.claim()[0]
        self.assertEqual(second_claim.envelope.id, published.message_id)
        self.assertNotEqual(second_claim.receipt, claim.receipt)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    unittest.main()
