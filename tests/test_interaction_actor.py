import asyncio
import concurrent.futures
import threading
import time
import unittest

from core.engine.interaction_actor import (
    InteractionActor,
    InteractionActorClosed,
    InteractionCancelled,
    InteractionQueueFull,
    InteractionReentrantCall,
)


class InteractionActorTests(unittest.TestCase):
    def test_fifty_producers_are_serialized_by_one_owner(self):
        lock = threading.Lock()
        active = 0
        max_active = 0
        owner_ids = set()

        def handler(request):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
                owner_ids.add(threading.get_ident())
            time.sleep(0.002)
            with lock:
                active -= 1
            return request.payload * 2

        actor = InteractionActor(handler, capacity=64)
        barrier = threading.Barrier(51)
        tickets = []
        tickets_lock = threading.Lock()

        def producer(value):
            barrier.wait()
            ticket = actor.submit(value, source="stress")
            with tickets_lock:
                tickets.append((value, ticket))

        producers = [
            threading.Thread(target=producer, args=(value,), daemon=True)
            for value in range(50)
        ]
        for producer_thread in producers:
            producer_thread.start()
        barrier.wait()
        for producer_thread in producers:
            producer_thread.join(2.0)

        self.assertEqual(len(tickets), 50)
        for value, ticket in tickets:
            self.assertEqual(ticket.result(timeout=3.0), value * 2)

        self.assertTrue(actor.shutdown(timeout=2.0))
        snapshot = actor.snapshot()
        self.assertEqual(max_active, 1)
        self.assertEqual(len(owner_ids), 1)
        self.assertEqual(snapshot.submitted, 50)
        self.assertEqual(snapshot.started, 50)
        self.assertEqual(snapshot.succeeded, 50)
        self.assertEqual(snapshot.failed, 0)

    def test_capacity_applies_backpressure_to_pending_work(self):
        active_started = threading.Event()
        release_active = threading.Event()

        def handler(request):
            if request.payload == "active":
                active_started.set()
                release_active.wait(2.0)
            return request.payload

        actor = InteractionActor(handler, capacity=1)
        active = actor.submit("active")
        self.assertTrue(active_started.wait(1.0))
        pending = actor.submit("pending")

        with self.assertRaises(InteractionQueueFull):
            actor.submit("rejected")

        snapshot = actor.snapshot()
        self.assertEqual(snapshot.queued, 1)
        self.assertEqual(snapshot.rejected_full, 1)
        release_active.set()
        self.assertEqual(active.result(timeout=1.0), "active")
        self.assertEqual(pending.result(timeout=1.0), "pending")
        self.assertTrue(actor.shutdown(timeout=1.0))

    def test_queued_cancellation_is_typed_and_never_runs(self):
        active_started = threading.Event()
        release_active = threading.Event()
        executed = []

        def handler(request):
            executed.append(request.payload)
            if request.payload == "active":
                active_started.set()
                release_active.wait(2.0)
            return request.payload

        actor = InteractionActor(handler, capacity=2)
        first = actor.submit("active")
        self.assertTrue(active_started.wait(1.0))
        queued = actor.submit("queued")

        self.assertTrue(queued.cancel("superseded"))
        with self.assertRaises(InteractionCancelled) as caught:
            queued.result(timeout=0.2)
        self.assertEqual(caught.exception.reason, "superseded")

        release_active.set()
        self.assertEqual(first.result(timeout=1.0), "active")
        self.assertTrue(actor.shutdown(timeout=1.0))
        self.assertEqual(executed, ["active"])
        self.assertEqual(actor.snapshot().cancelled, 1)

    def test_cancelled_pending_request_releases_capacity_immediately(self):
        active_started = threading.Event()
        release_active = threading.Event()

        def handler(request):
            if request.payload == "active":
                active_started.set()
                release_active.wait(2.0)
            return request.payload

        actor = InteractionActor(handler, capacity=1)
        active = actor.submit("active")
        self.assertTrue(active_started.wait(1.0))
        superseded = actor.submit("superseded")
        self.assertTrue(superseded.cancel("newer request"))

        replacement = actor.submit("replacement")
        self.assertEqual(actor.snapshot().queued, 1)
        with self.assertRaises(InteractionCancelled):
            superseded.result(timeout=0.2)

        release_active.set()
        self.assertEqual(active.result(timeout=1.0), "active")
        self.assertEqual(replacement.result(timeout=1.0), "replacement")
        self.assertTrue(actor.shutdown(timeout=1.0))

    def test_repeated_supersession_keeps_physical_queue_bounded(self):
        active_started = threading.Event()
        release_active = threading.Event()

        def handler(request):
            if request.payload == "active":
                active_started.set()
                release_active.wait(3.0)
            return request.payload

        actor = InteractionActor(handler, capacity=1)
        active = actor.submit("active")
        self.assertTrue(active_started.wait(1.0))

        for index in range(2_000):
            superseded = actor.submit(index)
            self.assertTrue(superseded.cancel("superseded"))
            with self.assertRaises(InteractionCancelled):
                superseded.result(timeout=0.1)
            self.assertEqual(actor.snapshot().queued, 0)
            self.assertLessEqual(len(actor._queue), 1)

        replacement = actor.submit("replacement")
        self.assertEqual(actor.snapshot().queued, 1)
        release_active.set()
        self.assertEqual(active.result(timeout=1.0), "active")
        self.assertEqual(replacement.result(timeout=1.0), "replacement")
        self.assertTrue(actor.shutdown(timeout=1.0))

    def test_active_cancellation_is_cooperative_and_typed(self):
        active_started = threading.Event()
        handler_stopped = threading.Event()

        def handler(request):
            active_started.set()
            while not request.cancel_event.wait(0.01):
                pass
            handler_stopped.set()
            request.raise_if_cancelled("handler observed cancellation")

        actor = InteractionActor(handler, capacity=1)
        ticket = actor.submit("active")
        self.assertTrue(active_started.wait(1.0))
        self.assertTrue(ticket.cancel("user interrupted"))
        with self.assertRaises(InteractionCancelled):
            ticket.result(timeout=1.0)

        self.assertTrue(handler_stopped.is_set())
        self.assertTrue(actor.shutdown(timeout=1.0))
        snapshot = actor.snapshot()
        self.assertEqual(snapshot.started, 1)
        self.assertEqual(snapshot.cancelled, 1)
        self.assertEqual(snapshot.succeeded, 0)

    def test_successful_handler_return_commits_despite_racing_cancel(self):
        side_effect_done = threading.Event()
        release_handler = threading.Event()
        committed_cleanup_started = threading.Event()
        release_cleanup = threading.Event()
        side_effect_count = 0

        def handler(request):
            nonlocal side_effect_count
            side_effect_count += 1
            side_effect_done.set()
            self.assertTrue(release_handler.wait(2.0))
            return {"receipt": request.request_id}

        def after_request(_request, _error):
            committed_cleanup_started.set()
            self.assertTrue(release_cleanup.wait(2.0))

        actor = InteractionActor(handler, capacity=1, after_request=after_request)
        ticket = actor.submit("non-idempotent", request_id="commit-race")
        self.assertTrue(side_effect_done.wait(1.0))

        # The request is still running, so cancellation signals the handler.
        # It deliberately returns success instead of accepting cancellation;
        # that return is the commit boundary and must not induce a retry.
        self.assertTrue(ticket.cancel("caller timed out"))
        self.assertTrue(ticket.cancel_event.is_set())
        release_handler.set()
        self.assertTrue(committed_cleanup_started.wait(1.0))

        # The handler has returned and committed, although lifecycle cleanup
        # deliberately keeps the Future pending. A later cancel must already
        # lose arbitration at this boundary.
        self.assertFalse(ticket.cancel("after commit"))
        release_cleanup.set()

        self.assertEqual(
            ticket.result(timeout=1.0),
            {"receipt": "commit-race"},
        )
        self.assertEqual(side_effect_count, 1)
        self.assertTrue(actor.shutdown(timeout=1.0))
        snapshot = actor.snapshot()
        self.assertEqual(snapshot.started, 1)
        self.assertEqual(snapshot.succeeded, 1)
        self.assertEqual(snapshot.cancelled, 0)
        self.assertEqual(snapshot.failed, 0)
        self.assertEqual(snapshot.cleanup_failed, 0)

    def test_cleanup_hook_failure_cannot_override_committed_result(self):
        side_effect_count = 0
        cleanup_calls = 0

        def handler(request):
            nonlocal side_effect_count
            side_effect_count += 1
            return {"receipt": request.request_id}

        def after_request(_request, _error):
            nonlocal cleanup_calls
            cleanup_calls += 1
            raise RuntimeError("cleanup failed after commit")

        actor = InteractionActor(handler, after_request=after_request)
        ticket = actor.submit("non-idempotent", request_id="cleanup-race")

        self.assertEqual(
            ticket.result(timeout=1.0),
            {"receipt": "cleanup-race"},
        )
        self.assertEqual(side_effect_count, 1)
        self.assertEqual(cleanup_calls, 1)
        self.assertTrue(actor.shutdown(timeout=1.0))
        snapshot = actor.snapshot()
        self.assertEqual(snapshot.succeeded, 1)
        self.assertEqual(snapshot.failed, 0)
        self.assertEqual(snapshot.cancelled, 0)
        self.assertEqual(snapshot.cleanup_failed, 1)

    def test_before_hook_failure_remains_a_precommit_failure(self):
        handler_calls = 0

        def before_request(_request):
            raise RuntimeError("admission failed")

        def handler(_request):
            nonlocal handler_calls
            handler_calls += 1
            return "must not run"

        actor = InteractionActor(handler, before_request=before_request)
        ticket = actor.submit("precommit")
        with self.assertRaisesRegex(RuntimeError, "admission failed"):
            ticket.result(timeout=1.0)

        self.assertEqual(handler_calls, 0)
        self.assertTrue(actor.shutdown(timeout=1.0))
        snapshot = actor.snapshot()
        self.assertEqual(snapshot.succeeded, 0)
        self.assertEqual(snapshot.failed, 1)
        self.assertEqual(snapshot.cleanup_failed, 0)

    def test_reentrant_sync_wait_is_rejected_without_deadlock(self):
        actor = None

        def handler(request):
            return actor.interact_sync("nested", timeout=0.1)

        actor = InteractionActor(handler, capacity=2)
        ticket = actor.submit("outer")
        with self.assertRaises(InteractionReentrantCall):
            ticket.result(timeout=1.0)

        self.assertTrue(actor.shutdown(timeout=1.0))
        self.assertEqual(actor.snapshot().failed, 1)

    def test_async_facade_does_not_block_event_loop(self):
        release = threading.Event()

        def handler(request):
            release.wait(1.0)
            return request.payload

        actor = InteractionActor(handler)

        async def scenario():
            interaction = asyncio.create_task(actor.interact_async("ok"))
            await asyncio.sleep(0.02)
            self.assertFalse(interaction.done())
            release.set()
            return await interaction

        self.assertEqual(asyncio.run(scenario()), "ok")
        self.assertTrue(actor.shutdown(timeout=1.0))

    def test_shutdown_cancels_active_and_queued_and_closes_admission(self):
        active_started = threading.Event()

        def handler(request):
            active_started.set()
            request.cancel_event.wait(2.0)
            request.raise_if_cancelled()

        actor = InteractionActor(handler, capacity=2)
        active = actor.submit("active")
        self.assertTrue(active_started.wait(1.0))
        queued = actor.submit("queued")

        self.assertTrue(actor.shutdown(drain=False, timeout=1.0))
        for ticket in (active, queued):
            with self.assertRaises(InteractionCancelled):
                ticket.result(timeout=0.2)
        with self.assertRaises(InteractionActorClosed):
            actor.submit("late")

        snapshot = actor.snapshot()
        self.assertTrue(snapshot.closed)
        self.assertFalse(snapshot.worker_alive)
        self.assertEqual(snapshot.cancelled, 2)

    def test_draining_shutdown_finishes_accepted_work(self):
        actor = InteractionActor(lambda request: request.payload, capacity=4)
        tickets = [actor.submit(value) for value in range(4)]

        self.assertTrue(actor.shutdown(drain=True, timeout=1.0))
        self.assertEqual([ticket.result() for ticket in tickets], list(range(4)))
        self.assertEqual(actor.snapshot().succeeded, 4)

    def test_shutdown_of_never_started_actor_is_bounded(self):
        actor = InteractionActor(lambda request: request.payload)
        started = time.monotonic()
        self.assertTrue(actor.shutdown(timeout=0.01))
        self.assertLess(time.monotonic() - started, 0.2)
        with self.assertRaises(InteractionActorClosed):
            actor.start()


if __name__ == "__main__":
    unittest.main()
