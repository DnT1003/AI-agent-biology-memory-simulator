import concurrent.futures
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from core.agent_state import AgentState, StateMachine
from core.engine.cognitive_engine import CognitiveEngine
from core.engine.interaction_actor import (
    InteractionActor,
    InteractionCancelled,
    InteractionRequest,
)
from core.event_journal import EventJournal, PRIVATE_EPHEMERAL, RotatingEventJournal
from core.state_projection import apply_projection_patch, projection_hash


def _make_engine(journal, handler, *, capacity=8):
    engine = CognitiveEngine.__new__(CognitiveEngine)
    engine.state_machine = StateMachine(AgentState.IDLE)
    engine._runtime_mutation_gate = threading.Lock()
    engine._interaction_state_lock = threading.Lock()
    engine._interaction_state_owner = None
    engine._journal_tracking_lock = threading.Lock()
    engine._journal_requests = {}
    engine.event_journal = journal
    engine.ego = SimpleNamespace(
        lock=threading.Lock(),
        mood=0.0,
        stress=0.0,
        fatigue=0.0,
        curiosity=0.5,
        social_need=0.5,
        integrity=1.0,
        energy=1.0,
        atp_level=1.0,
        is_identity_crisis=False,
    )
    engine.stm_lock = threading.Lock()
    engine.short_term_buffer = []
    engine.interaction = SimpleNamespace(
        interaction_loop=handler,
        _requires_local_backend=lambda text: text.startswith("/local"),
        _is_private_ephemeral_input=lambda text: text.startswith("/local"),
    )
    engine.memory_ops = SimpleNamespace(sleep=lambda: "slept")
    engine.interaction_actor = InteractionActor(
        engine._run_interaction_request,
        capacity=capacity,
        before_request=engine._before_interaction_request,
        after_request=engine._after_interaction_request,
    )
    return engine


class CognitiveEngineEventJournalTests(unittest.TestCase):
    @staticmethod
    def _request(request_id):
        return InteractionRequest(
            request_id=request_id,
            payload={"user_input": request_id, "private_ephemeral": False},
            source="test",
            cancel_event=threading.Event(),
            submitted_at=time.monotonic(),
        )

    def test_success_records_ordered_lifecycle_and_replayable_state_delta(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            journal = EventJournal(temp_dir)
            engine = None

            def handler(_text, **_kwargs):
                with engine.ego.lock:
                    engine.ego.mood = 0.25
                return {"response": "content-is-not-journaled"}

            engine = _make_engine(journal, handler)
            ticket = engine.submit_interaction(
                "hello", source="producer", request_id="request-1"
            )
            self.assertEqual(
                ticket.result(timeout=1.0),
                {"response": "content-is-not-journaled"},
            )
            self.assertTrue(engine.interaction_actor.shutdown(timeout=1.0))

            events = list(journal.iter_events())
            kinds = [event.event_type for event in events]
            self.assertEqual(kinds[0], "interaction.accepted")
            self.assertEqual(kinds[1], "interaction.started")
            self.assertEqual(kinds[-1], "interaction.finished")
            self.assertEqual(events[-1].outcome, "succeeded")
            self.assertTrue(events[-1].payload["response_present"])
            self.assertEqual({event.source for event in events}, {"unknown"})

            snapshot = next(
                event for event in events if event.event_type == "state.snapshot"
            )
            delta = next(
                event for event in events if event.event_type == "state.delta"
            )
            replayed = apply_projection_patch(
                snapshot.payload["projection"], delta.payload["patch"]
            )
            self.assertEqual(
                projection_hash(replayed), delta.payload["after_hash"]
            )
            self.assertEqual(replayed["ego"]["mood"], 0.25)

            serialized = "".join(
                path.read_text(encoding="utf-8")
                for path in journal.events_dir.iterdir()
                if path.is_file() and path.suffix == ".json"
            )
            self.assertNotIn("content-is-not-journaled", serialized)
            self.assertNotIn("hello", serialized)

    def test_private_interaction_erases_every_event_payload(self):
        secret = "PRIVATE-SENTINEL"
        with tempfile.TemporaryDirectory() as temp_dir:
            journal = EventJournal(temp_dir)
            engine = _make_engine(
                journal,
                lambda _text, **_kwargs: {"response": secret},
            )
            ticket = engine.submit_interaction(
                f"/local {secret}", source="web", request_id=secret
            )
            self.assertEqual(ticket.result(timeout=1.0), {"response": secret})
            self.assertTrue(engine.interaction_actor.shutdown(timeout=1.0))

            events = list(journal.iter_events())
            self.assertTrue(events)
            self.assertTrue(
                all(event.privacy == PRIVATE_EPHEMERAL for event in events)
            )
            self.assertTrue(all(event.payload == {} for event in events))
            serialized = "".join(
                path.read_text(encoding="utf-8")
                for path in Path(journal.events_dir).glob("*.json")
            )
            self.assertNotIn(secret, serialized)

    def test_queued_cancellation_has_one_terminal_event_and_no_started_event(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            journal = EventJournal(temp_dir)
            first_started = threading.Event()
            release_first = threading.Event()

            def handler(text, **_kwargs):
                if text == "first":
                    first_started.set()
                    release_first.wait(1.0)
                return {"response": text}

            engine = _make_engine(journal, handler, capacity=2)
            first = engine.submit_interaction("first", request_id="first")
            self.assertTrue(first_started.wait(1.0))
            queued = engine.submit_interaction("second", request_id="queued")
            self.assertTrue(queued.cancel("test cancellation"))
            with self.assertRaises(InteractionCancelled):
                queued.result(timeout=1.0)
            release_first.set()
            self.assertEqual(first.result(timeout=1.0), {"response": "first"})
            self.assertTrue(engine.interaction_actor.shutdown(timeout=1.0))

            queued_events = [
                event for event in journal.iter_events()
                if event.request_id == "queued"
            ]
            self.assertEqual(
                [event.event_type for event in queued_events],
                ["interaction.accepted", "interaction.finished"],
            )
            self.assertEqual(queued_events[-1].outcome, "cancelled")

    def test_cancel_racing_committed_handler_is_journaled_as_success(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            journal = EventJournal(temp_dir)
            side_effect_done = threading.Event()
            release_handler = threading.Event()
            side_effect_count = 0

            def handler(text, **_kwargs):
                nonlocal side_effect_count
                side_effect_count += 1
                side_effect_done.set()
                self.assertTrue(release_handler.wait(1.0))
                return {"response": text}

            engine = _make_engine(journal, handler)
            ticket = engine.submit_interaction(
                "commit once", request_id="committed-race"
            )
            self.assertTrue(side_effect_done.wait(1.0))
            self.assertTrue(ticket.cancel("late caller timeout"))
            release_handler.set()

            self.assertEqual(
                ticket.result(timeout=1.0), {"response": "commit once"}
            )
            self.assertEqual(side_effect_count, 1)
            self.assertTrue(engine.interaction_actor.shutdown(timeout=1.0))

            request_events = [
                event
                for event in journal.iter_events()
                if event.request_id == "committed-race"
            ]
            self.assertEqual(request_events[-1].event_type, "interaction.finished")
            self.assertEqual(request_events[-1].outcome, "succeeded")

    def test_interaction_span_stays_in_accepted_run_during_concurrent_rotation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            rotating = RotatingEventJournal(temp_dir, max_events=1)
            engine = CognitiveEngine.__new__(CognitiveEngine)
            engine._journal_tracking_lock = threading.Lock()
            engine._journal_requests = {}
            engine.event_journal = rotating
            first = self._request("first-span")
            second = self._request("second-root")
            first_accepted = threading.Event()
            second_rotated = threading.Event()
            errors = []
            first_run_ids = []

            def run_first_span():
                try:
                    state = engine._ensure_journal_accepted(first)
                    first_run_ids.append(state.journal.run_id)
                    first_accepted.set()
                    self.assertTrue(second_rotated.wait(1.0))
                    engine._activate_request_journal(first)
                    engine._reset_request_journal(first)
                    future = concurrent.futures.Future()
                    future.set_result({"response": "never-persisted"})
                    engine._finish_request_journal(first, future)
                except BaseException as exc:  # surfaced on the test thread
                    errors.append(exc)
                    first_accepted.set()

            def rotate_with_second_root():
                try:
                    self.assertTrue(first_accepted.wait(1.0))
                    engine._ensure_journal_accepted(second)
                except BaseException as exc:  # surfaced on the test thread
                    errors.append(exc)
                finally:
                    second_rotated.set()

            first_thread = threading.Thread(target=run_first_span)
            second_thread = threading.Thread(target=rotate_with_second_root)
            first_thread.start()
            second_thread.start()
            first_thread.join(2.0)
            second_thread.join(2.0)
            self.assertFalse(first_thread.is_alive())
            self.assertFalse(second_thread.is_alive())
            self.assertEqual(errors, [])

            old_run_id = first_run_ids[0]
            new_run_id = rotating.run_id
            self.assertNotEqual(new_run_id, old_run_id)
            old_events = list(
                EventJournal(temp_dir, run_id=old_run_id, create=False).iter_events()
            )
            new_events = list(
                EventJournal(temp_dir, run_id=new_run_id, create=False).iter_events()
            )
            self.assertEqual(
                [event.event_type for event in old_events],
                [
                    "interaction.accepted",
                    "interaction.started",
                    "interaction.finished",
                ],
            )
            self.assertEqual(
                {event.request_id for event in old_events}, {"first-span"}
            )
            self.assertEqual(
                [event.event_type for event in new_events],
                ["journal.run_started", "interaction.accepted"],
            )

    def test_tick_journal_failure_does_not_change_cadence_or_result(self):
        engine = CognitiveEngine.__new__(CognitiveEngine)
        engine._runtime_mutation_gate = threading.Lock()
        engine.state_machine = StateMachine(AgentState.IDLE)
        engine._state_duration_mix = Mock(return_value=({}, {AgentState.IDLE: 1.0}))
        engine._cognitive_tick_owned = Mock(return_value=True)
        engine.event_journal = SimpleNamespace(
            append_safe=Mock(side_effect=RuntimeError("journal unavailable"))
        )

        self.assertTrue(engine.cognitive_tick(12.5))
        engine._cognitive_tick_owned.assert_called_once()
        self.assertTrue(engine._runtime_mutation_gate.acquire(blocking=False))
        engine._runtime_mutation_gate.release()

    def test_tick_span_has_replayable_state_and_exact_terminal_event(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            journal = EventJournal(temp_dir)
            engine = _make_engine(
                journal,
                lambda _text, **_kwargs: {"response": "unused"},
            )
            engine._state_duration_mix = Mock(
                return_value=({AgentState.IDLE: 7.0}, {AgentState.IDLE: 7.0})
            )

            def tick_owned(*_args, **_kwargs):
                with engine.ego.lock:
                    engine.ego.stress = 0.2
                return True

            engine._cognitive_tick_owned = Mock(side_effect=tick_owned)

            self.assertTrue(engine.cognitive_tick(7.0))
            events = list(journal.iter_events())
            self.assertEqual(events[0].event_type, "cognitive_tick.started")
            self.assertEqual(events[-1].event_type, "cognitive_tick.finished")
            self.assertEqual(events[-1].outcome, "succeeded")
            self.assertEqual(
                {event.correlation_id for event in events},
                {events[0].correlation_id},
            )
            self.assertTrue(events[0].correlation_id.startswith("tick:"))
            snapshot = next(
                event for event in events if event.event_type == "state.snapshot"
            )
            delta = next(
                event for event in events if event.event_type == "state.delta"
            )
            replayed = apply_projection_patch(
                snapshot.payload["projection"], delta.payload["patch"]
            )
            self.assertEqual(projection_hash(replayed), delta.payload["after_hash"])
            self.assertEqual(replayed["ego"]["stress"], 0.2)

    def test_tick_journal_distinguishes_postcommit_failure_and_cancellation(self):
        cases = (
            ("failed", "RuntimeError"),
            ("cancelled", None),
        )
        for maintenance_status, error_type in cases:
            with self.subTest(maintenance_status=maintenance_status), tempfile.TemporaryDirectory() as temp_dir:
                journal = EventJournal(temp_dir)
                engine = _make_engine(
                    journal,
                    lambda _text, **_kwargs: {"response": "unused"},
                )
                duration_snapshot = {AgentState.IDLE: 5.0}
                engine._state_duration_checkpoint = {}
                engine._state_duration_mix = Mock(
                    return_value=(
                        {AgentState.IDLE: 5.0},
                        duration_snapshot,
                    )
                )

                def tick_owned(*_args, **kwargs):
                    status = kwargs["execution_status"]
                    status.update(
                        biology_status="committed",
                        maintenance_status=maintenance_status,
                        phase="memory",
                        outcome=maintenance_status,
                    )
                    if error_type is not None:
                        status["error_type"] = error_type
                    return True

                engine._cognitive_tick_owned = Mock(side_effect=tick_owned)

                self.assertTrue(engine.cognitive_tick(5.0))
                self.assertEqual(
                    engine._state_duration_checkpoint,
                    duration_snapshot,
                )
                finished = list(journal.iter_events())[-1]
                self.assertEqual(finished.outcome, maintenance_status)
                self.assertEqual(
                    finished.payload["biology_status"], "committed"
                )
                self.assertEqual(
                    finished.payload["maintenance_status"],
                    maintenance_status,
                )
                self.assertEqual(finished.payload["phase"], "memory")
                if error_type is None:
                    self.assertNotIn("error_type", finished.payload)
                else:
                    self.assertEqual(
                        finished.payload["error_type"], error_type
                    )
                self.assertTrue(engine.interaction_actor.shutdown(timeout=1.0))

    def test_tick_span_stays_in_started_run_during_interaction_rotation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            rotating = RotatingEventJournal(temp_dir, max_events=1)
            engine = _make_engine(
                rotating,
                lambda _text, **_kwargs: {"response": "unused"},
            )
            engine._state_duration_mix = Mock(
                return_value=({AgentState.IDLE: 4.0}, {AgentState.IDLE: 4.0})
            )
            tick_started = threading.Event()
            allow_tick_finish = threading.Event()
            tick_results = []
            tick_errors = []

            def tick_owned(*_args, **_kwargs):
                tick_started.set()
                if not allow_tick_finish.wait(1.0):
                    raise TimeoutError("test did not rotate journal")
                return True

            engine._cognitive_tick_owned = Mock(side_effect=tick_owned)

            def run_tick():
                try:
                    tick_results.append(engine.cognitive_tick(4.0))
                except BaseException as exc:  # surfaced on the test thread
                    tick_errors.append(exc)

            old_run_id = rotating.run_id
            tick_thread = threading.Thread(target=run_tick)
            tick_thread.start()
            self.assertTrue(tick_started.wait(1.0))
            engine._ensure_journal_accepted(self._request("rotate-during-tick"))
            new_run_id = rotating.run_id
            self.assertNotEqual(new_run_id, old_run_id)
            allow_tick_finish.set()
            tick_thread.join(2.0)
            self.assertFalse(tick_thread.is_alive())
            self.assertEqual(tick_errors, [])
            self.assertEqual(tick_results, [True])

            old_events = list(
                EventJournal(temp_dir, run_id=old_run_id, create=False).iter_events()
            )
            new_events = list(
                EventJournal(temp_dir, run_id=new_run_id, create=False).iter_events()
            )
            self.assertEqual(
                [event.event_type for event in old_events],
                [
                    "cognitive_tick.started",
                    "state.snapshot",
                    "state.delta",
                    "cognitive_tick.finished",
                ],
            )
            self.assertEqual(
                [event.event_type for event in new_events],
                ["journal.run_started", "interaction.accepted"],
            )
            self.assertTrue(engine.interaction_actor.shutdown(timeout=1.0))

    def test_precommit_tick_failure_rolls_back_and_is_journaled_as_failed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            journal = EventJournal(temp_dir)
            engine = _make_engine(
                journal,
                lambda _text, **_kwargs: {"response": "unused"},
            )
            engine._state_duration_checkpoint = {}
            # The minimal ego deliberately lacks apply_biological_decay, so
            # the real tick must restore its first bounded mutation and retain
            # the duration checkpoint for a safe retry.
            engine.last_interaction_time = 0.0
            initial_fatigue = engine.ego.fatigue

            self.assertFalse(engine.cognitive_tick(1.0))
            self.assertEqual(engine.ego.fatigue, initial_fatigue)
            self.assertEqual(engine._state_duration_checkpoint, {})
            finished = list(journal.iter_events())[-1]
            self.assertEqual(finished.event_type, "cognitive_tick.finished")
            self.assertEqual(finished.outcome, "failed")
            self.assertEqual(finished.payload["error_type"], "AttributeError")
            self.assertEqual(finished.payload["biology_status"], "rolled_back")
            self.assertEqual(
                finished.payload["maintenance_status"], "not_started"
            )
            self.assertEqual(finished.payload["phase"], "biology")


if __name__ == "__main__":
    unittest.main()
