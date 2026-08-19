import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from config import Config
from components.llm import CloudTransportError
from core.agent_state import AgentState, StateMachine
from core.engine.cognitive_engine import CognitiveEngine
from core.engine.interaction import InteractionController, InteractionOutputError
from core.engine.interaction_actor import InteractionActor, InteractionCancelled
from core.engine.memory_ops import MemoryOperationsController
from core.engine.perception import PerceptionController


class _RecordingStateMachine(StateMachine):
    def __init__(self, initial=AgentState.IDLE):
        super().__init__(initial)
        self.transitions = []
        self._transitions_lock = threading.Lock()

    def transition(self, new_state):
        changed = super().transition(new_state)
        if changed:
            with self._transitions_lock:
                self.transitions.append(new_state)
        return changed


def _make_adapter_engine(handler, *, initial=AgentState.IDLE, capacity=64):
    """Build only the CognitiveEngine/actor boundary, without models or DBs."""

    engine = CognitiveEngine.__new__(CognitiveEngine)
    engine.state_machine = _RecordingStateMachine(initial)
    engine._runtime_mutation_gate = threading.Lock()
    engine._interaction_state_lock = threading.Lock()
    engine._interaction_state_owner = None
    engine.interaction = SimpleNamespace(
        interaction_loop=handler,
        _forces_local_input=lambda _text: False,
        _requires_local_backend=lambda _text: False,
        _is_private_ephemeral_input=lambda _text: False,
    )
    engine.memory_ops = SimpleNamespace(sleep=lambda: "slept")
    engine.interaction_actor = InteractionActor(
        engine._run_interaction_request,
        capacity=capacity,
        before_request=engine._before_interaction_request,
        after_request=engine._after_interaction_request,
    )
    return engine


class CognitiveEngineActorIntegrationTests(unittest.TestCase):
    def test_adapter_payload_is_an_immutable_privacy_snapshot(self):
        observed = []

        def interaction_loop(
            user_input,
            is_deep_mode=False,
            model_override=None,
            cancel_event=None,
            force_local=False,
            private_ephemeral=False,
            request_id=None,
        ):
            observed.append(
                (user_input, force_local, private_ephemeral, request_id)
            )
            return {"response": "ok"}

        engine = _make_adapter_engine(interaction_loop)
        engine.interaction._requires_local_backend = lambda text: text.startswith("/local")
        engine.interaction._is_private_ephemeral_input = lambda text: text.startswith("/local")
        ticket = engine.submit_interaction("/local immutable-secret")

        with self.assertRaises(TypeError):
            ticket.request.payload["force_local"] = False
        with self.assertRaises(TypeError):
            ticket.request.payload["user_input"] = "public replacement"

        self.assertEqual(ticket.result(timeout=1.0), {"response": "ok"})
        self.assertEqual(
            observed,
            [("/local immutable-secret", True, True, ticket.request_id)],
        )
        self.assertTrue(engine.interaction_actor.shutdown(timeout=1.0))

    def test_adapter_serializes_producers_and_owns_thinking_state(self):
        metrics_lock = threading.Lock()
        active = 0
        max_active = 0
        states_seen = []
        engine = None

        def interaction_loop(
            user_input,
            is_deep_mode=False,
            model_override=None,
            cancel_event=None,
            force_local=False,
            private_ephemeral=False,
            request_id=None,
        ):
            nonlocal active, max_active
            with metrics_lock:
                active += 1
                max_active = max(max_active, active)
                states_seen.append(engine.state_machine.state)
            time.sleep(0.003)
            with metrics_lock:
                active -= 1
            return {"response": user_input}

        engine = _make_adapter_engine(interaction_loop, capacity=32)
        barrier = threading.Barrier(11)
        tickets = []
        tickets_lock = threading.Lock()

        def producer(index):
            barrier.wait()
            ticket = engine.submit_interaction(str(index), source="producer")
            with tickets_lock:
                tickets.append((index, ticket))

        threads = [
            threading.Thread(target=producer, args=(index,), daemon=True)
            for index in range(10)
        ]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(1.0)

        self.assertEqual(len(tickets), 10)
        for index, ticket in tickets:
            self.assertEqual(ticket.result(timeout=2.0), {"response": str(index)})

        self.assertTrue(engine.interaction_actor.shutdown(timeout=1.0))
        self.assertEqual(max_active, 1)
        self.assertEqual(states_seen, [AgentState.THINKING] * 10)
        self.assertEqual(engine.state_machine.state, AgentState.IDLE)
        self.assertEqual(
            engine.state_machine.transitions,
            [AgentState.THINKING, AgentState.IDLE] * 10,
        )
        self.assertIsNone(engine._interaction_state_owner)

    def test_failed_before_hook_never_releases_autonomous_thinking_state(self):
        handler = Mock(return_value={"response": "must not run"})
        engine = _make_adapter_engine(handler, initial=AgentState.THINKING)
        engine._interaction_state_owner = "autonomous-owner"
        self.assertTrue(engine._runtime_mutation_gate.acquire(blocking=False))

        with patch.object(
            Config, "INTERACTION_STATE_WAIT_SECONDS", 0.1, create=True
        ):
            timed_out = engine.submit_interaction("wait", request_id="timed-out")
            with self.assertRaises(TimeoutError):
                timed_out.result(timeout=1.0)

        self.assertEqual(engine.state_machine.state, AgentState.THINKING)
        self.assertEqual(engine._interaction_state_owner, "autonomous-owner")
        self.assertTrue(engine._runtime_mutation_gate.locked())

        with patch.object(
            Config, "INTERACTION_STATE_WAIT_SECONDS", 5.0, create=True
        ):
            cancelled = engine.submit_interaction(
                "cancel while waiting", request_id="cancelled-waiter"
            )
            deadline = time.monotonic() + 1.0
            while (
                engine.interaction_actor.snapshot().active_request_id
                != cancelled.request_id
                and time.monotonic() < deadline
            ):
                time.sleep(0.005)
            self.assertEqual(
                engine.interaction_actor.snapshot().active_request_id,
                cancelled.request_id,
            )
            self.assertTrue(cancelled.cancel("caller left"))
            with self.assertRaises(InteractionCancelled):
                cancelled.result(timeout=1.0)

        self.assertEqual(engine.state_machine.state, AgentState.THINKING)
        self.assertEqual(engine._interaction_state_owner, "autonomous-owner")
        self.assertTrue(engine._runtime_mutation_gate.locked())
        handler.assert_not_called()
        self.assertTrue(engine.interaction_actor.shutdown(drain=False, timeout=1.0))
        engine._runtime_mutation_gate.release()

    def test_cancellation_event_is_scoped_to_exactly_one_request(self):
        first_started = threading.Event()
        events_by_input = {}

        def interaction_loop(
            user_input,
            is_deep_mode=False,
            model_override=None,
            cancel_event=None,
            force_local=False,
            private_ephemeral=False,
            request_id=None,
        ):
            events_by_input[user_input] = cancel_event
            if user_input == "first":
                first_started.set()
                cancel_event.wait(1.0)
            return {"response": user_input}

        engine = _make_adapter_engine(interaction_loop, capacity=2)
        first = engine.submit_interaction("first", request_id="first-request")
        self.assertTrue(first_started.wait(1.0))
        second = engine.submit_interaction("second", request_id="second-request")

        self.assertTrue(first.cancel("superseded"))
        # This handler observes the event but returns normally, so its result
        # is committed. Cooperative handlers that want cancellation to win
        # must raise before returning (covered by the actor-level contract).
        self.assertEqual(first.result(timeout=1.0), {"response": "first"})
        self.assertEqual(second.result(timeout=1.0), {"response": "second"})

        self.assertIsNot(events_by_input["first"], events_by_input["second"])
        self.assertTrue(events_by_input["first"].is_set())
        self.assertFalse(events_by_input["second"].is_set())
        self.assertEqual(engine.state_machine.state, AgentState.IDLE)
        self.assertTrue(engine.interaction_actor.shutdown(timeout=1.0))


class InteractionShortcutContractTests(unittest.TestCase):
    @staticmethod
    def _controller(*, fatigue=0.0, mood=0.0, novel_loaded=True):
        ego = SimpleNamespace(
            lock=threading.Lock(),
            social_need=0.5,
            fatigue=fatigue,
            fatigue_critical=0.95,
            mood=mood,
            depression_critical=-0.95,
        )
        engine = SimpleNamespace(
            ego=ego,
            reader=SimpleNamespace(
                set_novel_by_url=Mock(return_value=novel_loaded)
            ),
            stm_lock=threading.Lock(),
            short_term_buffer=[],
            memory_ops=SimpleNamespace(
                save_short_term_memory=Mock(),
                sleep=Mock(),
            ),
            memory=SimpleNamespace(get_all=Mock(return_value=[])),
        )
        controller = object.__new__(InteractionController)
        controller.engine = engine
        return controller, engine

    def test_docln_shortcut_returns_a_typed_user_visible_response(self):
        controller, engine = self._controller()

        with patch.object(Config, "USE_LOCAL_ONLY", False), patch.object(
            Config, "FORCE_LOCAL_COMMANDS", ["/local"]
        ), patch("builtins.print"):
            result = controller.interaction_loop("https://docln.net/a-test-novel")

        self.assertIsInstance(result, dict)
        self.assertTrue(result["response"].strip())
        engine.reader.set_novel_by_url.assert_called_once()
        engine.memory_ops.save_short_term_memory.assert_called_once()

    def test_docln_shortcut_honors_cancellation_before_reader_commit(self):
        controller, engine = self._controller()
        cancel_event = threading.Event()

        def cancel_on_notice(*_args, **_kwargs):
            cancel_event.set()

        with patch.object(Config, "USE_LOCAL_ONLY", False), patch.object(
            Config, "FORCE_LOCAL_COMMANDS", ["/local"]
        ), patch(
            "builtins.print", side_effect=cancel_on_notice
        ), self.assertRaises(InteractionCancelled) as caught:
            controller.interaction_loop(
                "https://docln.net/a-test-novel",
                cancel_event=cancel_event,
                request_id="reader-cancel-id",
            )

        self.assertEqual(caught.exception.request_id, "reader-cancel-id")
        engine.reader.set_novel_by_url.assert_not_called()

    def test_sleep_shortcut_returns_a_typed_user_visible_response(self):
        controller, engine = self._controller()

        with patch.object(Config, "USE_LOCAL_ONLY", False), patch.object(
            Config, "FORCE_LOCAL_COMMANDS", ["/local"]
        ), patch("builtins.print"):
            result = controller.interaction_loop("ngủ ngon")

        self.assertIsInstance(result, dict)
        self.assertTrue(result["response"].strip())
        engine.memory_ops.sleep.assert_called_once_with()

    def test_sleep_shortcut_rechecks_cancellation_after_console_notice(self):
        controller, engine = self._controller()
        cancel_event = threading.Event()

        def cancel_on_notice(*_args, **_kwargs):
            cancel_event.set()

        with patch.object(Config, "USE_LOCAL_ONLY", False), patch.object(
            Config, "FORCE_LOCAL_COMMANDS", ["/local"]
        ), patch(
            "builtins.print", side_effect=cancel_on_notice
        ), self.assertRaises(InteractionCancelled):
            controller.interaction_loop(
                "ngủ ngon",
                cancel_event=cancel_event,
                request_id="sleep-notice-cancel-id",
            )

        engine.memory_ops.sleep.assert_not_called()

    def test_fatigue_shortcut_returns_a_typed_user_visible_response(self):
        controller, engine = self._controller(fatigue=1.0)

        with patch.object(Config, "USE_LOCAL_ONLY", False), patch.object(
            Config, "FORCE_LOCAL_COMMANDS", ["/local"]
        ), patch("builtins.print"):
            result = controller.interaction_loop("hello")

        self.assertIsInstance(result, dict)
        self.assertTrue(result["response"].strip())
        engine.memory_ops.sleep.assert_called_once_with()

    def test_depression_shortcut_returns_a_typed_user_visible_response(self):
        controller, engine = self._controller(mood=-1.0)

        with patch.object(Config, "USE_LOCAL_ONLY", False), patch.object(
            Config, "FORCE_LOCAL_COMMANDS", ["/local"]
        ), patch("random.random", return_value=0.0), patch("builtins.print"):
            result = controller.interaction_loop("hello")

        self.assertIsInstance(result, dict)
        self.assertTrue(result["response"].strip())
        engine.memory_ops.sleep.assert_not_called()

    def test_depression_shortcut_honors_cancellation_before_commit(self):
        controller, engine = self._controller(mood=-1.0)
        cancel_event = threading.Event()

        def cancel_while_selecting_branch():
            cancel_event.set()
            return 0.0

        with patch.object(Config, "USE_LOCAL_ONLY", False), patch.object(
            Config, "FORCE_LOCAL_COMMANDS", ["/local"]
        ), patch(
            "random.random", side_effect=cancel_while_selecting_branch
        ), patch("builtins.print"), self.assertRaises(
            InteractionCancelled
        ) as caught:
            controller.interaction_loop(
                "hello",
                cancel_event=cancel_event,
                request_id="depression-cancel-id",
            )

        self.assertEqual(caught.exception.request_id, "depression-cancel-id")
        engine.memory.get_all.assert_not_called()


class InteractionPrimaryOutputContractTests(unittest.TestCase):
    def test_minimal_response_is_normalized_to_safe_typed_defaults(self):
        normalized = InteractionController._normalize_primary_output(
            {"response": "  hello  "}, force_local=False
        )

        self.assertEqual(
            normalized,
            {
                "valence": 0.0,
                "arousal": 0.0,
                "importance": 0.5,
                "type": "episodic",
                "internal_monologue": "Trống rỗng...",
                "thought": "",
                "action": None,
                "response": "hello",
            },
        )

    def test_nonfinite_out_of_range_and_wrong_typed_fields_are_rejected(self):
        base = {
            "response": "ok",
            "valence": 0.0,
            "arousal": 0.2,
            "importance": 0.5,
            "type": "episodic",
            "internal_monologue": "test",
            "thought": "test",
            "action": None,
        }
        malformed = (
            ("valence", True),
            ("valence", float("nan")),
            ("valence", -1.1),
            ("arousal", -0.1),
            ("importance", 1.1),
            ("type", "unknown"),
            ("internal_monologue", None),
            ("thought", []),
            ("response", 7),
            ("action", {}),
        )

        for field, value in malformed:
            with self.subTest(field=field, value=value):
                payload = dict(base)
                payload[field] = value
                with self.assertRaises(InteractionOutputError):
                    InteractionController._normalize_primary_output(
                        payload, force_local=False
                    )

    def test_action_only_output_is_public_only(self):
        payload = {"response": "", "action": "search_novel|query"}

        normalized = InteractionController._normalize_primary_output(
            payload, force_local=False
        )
        self.assertEqual(normalized["action"], "search_novel|query")
        with self.assertRaises(InteractionOutputError):
            InteractionController._normalize_primary_output(
                {"response": "already answered", "action": "search_novel|query"},
                force_local=False,
            )
        with self.assertRaises(InteractionOutputError):
            InteractionController._normalize_primary_output(
                payload, force_local=True
            )


class _PrivacyEgo:
    def __init__(self):
        self.lock = threading.Lock()
        self.name = "Aura"
        self.traumas = []
        self.is_stranger = False
        self.evolved_insight = "test persona"
        self.current_intimacy = 0.5
        self.actionable_lessons = []
        self.fatigue = 0.0
        self.fatigue_critical = 0.95
        self.social_need = 0.5
        self.curiosity = 0.0
        self.mood = 0.0
        self.stress = 0.0
        self.integrity = 1.0
        self.energy = 1.0
        self.depression_critical = -0.95
        self.depression_severe = -0.8
        self.mania_severe = 0.8
        self.stress_critical = 0.95
        self.stress_severe = 0.8
        self.is_identity_crisis = False
        self.vocabulary = []
        self.updated_states = []
        self.semantic_belief_reads = 0
        self.local_belief_reads = 0

    def get_active_beliefs(self, *args, **kwargs):
        self.semantic_belief_reads += 1
        return []

    def get_active_beliefs_local(self):
        self.local_belief_reads += 1
        return []

    def get_interoceptive_prompt(self):
        return "stable"

    def update_state(self, result):
        self.updated_states.append(dict(result))

    def apply_circadian_rhythm(self):
        return None


class _PrivacyLLM:
    def __init__(self, sentinel):
        self.sentinel = sentinel
        self.calls = []

    def _record(self, kind, prompt, force_local):
        prompt = str(prompt)
        self.calls.append((kind, prompt, bool(force_local)))
        if not force_local and self.sentinel in prompt:
            raise AssertionError("hard-local input reached a cloud LLM call")

    def generate_text(self, prompt, *args, force_local=False, **kwargs):
        self._record("text", prompt, force_local)
        # The arousal parser appends a numeric fallback, so [] is also a stable
        # offline response for that call while remaining valid value JSON.
        return "[]", 0.0

    def generate_json(self, prompt, *args, force_local=False, **kwargs):
        self._record("json", prompt, force_local)
        return {
            "valence": 0.0,
            "arousal": 0.1,
            "importance": 0.5,
            "type": "episodic",
            "internal_monologue": "concise",
            "thought": "concise",
            "action": None,
            "response": "acknowledged",
        }, 0.0


class _PrivacyMemory:
    def __init__(self, sentinel):
        self.sentinel = sentinel
        self.search_queries = []
        self.added = []
        self.store = SimpleNamespace(
            update_meta=Mock(),
            update_vector=Mock(),
        )

    def search_memories(self, query, top_k=1, **_kwargs):
        query = str(query)
        if self.sentinel in query:
            raise AssertionError("hard-local input reached vector/embed search")
        self.search_queries.append(query)
        return []

    def chronological_recall(self, *args, **kwargs):
        return []

    def get_all(self):
        return []

    def add_memory(self, memory):
        if self.sentinel in getattr(memory, "content", ""):
            raise AssertionError("hard-local input was persisted as memory")
        self.added.append(memory)

    def enforce_garbage_collection(self):
        return None


class _RemotePerceptionSpy:
    mode = "remote"

    def __init__(self, sentinel):
        self.sentinel = sentinel
        self.calls = []

    def analyze(self, text):
        if self.sentinel in text:
            raise AssertionError("hard-local input reached remote LocalPerception")
        self.calls.append(text)
        return {"valence": 0.0, "arousal": 0.0, "confidence": 1.0}


class HardLocalRuntimePrivacyTests(unittest.TestCase):
    def test_cloud_or_schema_failure_is_not_persisted_as_placeholder_success(self):
        engine = SimpleNamespace()
        engine.ego = _PrivacyEgo()
        engine.stm_lock = threading.Lock()
        engine.short_term_buffer = ["User: stable history"]
        engine.memory = SimpleNamespace(get_all=Mock(return_value=[]))
        engine.world_graph = SimpleNamespace(query=Mock(return_value=[]))
        engine.memory_ops = SimpleNamespace(
            _apply_fog_masking=lambda text: text,
            update_or_add_memory=Mock(),
            save_short_term_memory=Mock(),
            sleep=Mock(),
        )
        engine.perception_ops = SimpleNamespace(
            get_sensory_summary=Mock(return_value="neutral")
        )
        engine.skills = SimpleNamespace(
            get_prompt_instructions=Mock(return_value=""), execute=Mock()
        )
        engine.reader = SimpleNamespace(get_status=Mock(return_value="idle"))
        engine.value_system = SimpleNamespace(get_moral_context=Mock(return_value=""))
        engine.llm = SimpleNamespace(
            generate_json=Mock(
                side_effect=CloudTransportError("provider unavailable")
            )
        )

        controller = InteractionController(engine)
        controller.compressor = SimpleNamespace(compress=Mock(return_value=[]))
        controller.reflex_gate = SimpleNamespace(
            evaluate_reflexes=Mock(return_value={"triggered": False})
        )

        with patch("builtins.print"), self.assertRaises(CloudTransportError):
            controller.perceive_and_respond("request that must fail", [])

        engine.llm.generate_json.side_effect = None
        engine.llm.generate_json.return_value = ({}, 0.0)
        with patch("builtins.print"), self.assertRaises(InteractionOutputError):
            controller.perceive_and_respond("invalid empty object", [])

        engine.llm.generate_json.return_value = (
            {
                "response": "looks valid until the emotional fields are read",
                "action": "dangerous_tool|payload",
                "valence": "not-a-number",
                "arousal": 0.2,
                "importance": 0.5,
                "type": "episodic",
                "internal_monologue": "test",
                "thought": "test",
            },
            0.0,
        )
        with patch("builtins.print"), self.assertRaises(InteractionOutputError):
            controller.perceive_and_respond("invalid typed fields", [])

        self.assertEqual(engine.ego.updated_states, [])
        self.assertEqual(engine.short_term_buffer, ["User: stable history"])
        engine.skills.execute.assert_not_called()
        engine.memory_ops.update_or_add_memory.assert_not_called()
        engine.memory_ops.save_short_term_memory.assert_not_called()

    def test_hard_local_is_ephemeral_and_cannot_taint_next_cloud_request(self):
        sentinel = "SECRET_SENTINEL"
        hard_local_input = f"/local {sentinel}"
        public_input = "ordinary public follow-up"

        engine = SimpleNamespace()
        engine.ego = _PrivacyEgo()
        engine.stm_lock = threading.Lock()
        engine.short_term_buffer = ["User: prior public context"]
        engine.llm = _PrivacyLLM(sentinel)
        engine.memory = _PrivacyMemory(sentinel)
        engine.embedder = SimpleNamespace(
            encode=Mock(
                side_effect=lambda text: (
                    (_ for _ in ()).throw(
                        AssertionError("hard-local input reached embedder")
                    )
                    if sentinel in str(text)
                    else [0.0]
                )
            )
        )
        engine.local_perception = _RemotePerceptionSpy(sentinel)
        engine.world_graph = SimpleNamespace(
            nodes={},
            query=Mock(return_value=[]),
            update_from_text=Mock(),
        )
        engine.value_system = SimpleNamespace(
            get_moral_context=Mock(return_value=""),
            update_user_value=Mock(),
            update_user_values_batch=Mock(),
        )
        engine.skills = SimpleNamespace(
            get_prompt_instructions=Mock(return_value="network_tool"),
            execute=Mock(),
        )
        engine.reader = SimpleNamespace(
            get_status=Mock(return_value="idle"),
            set_novel_by_url=Mock(),
        )
        engine._dump_mind_state = Mock()

        memory_ops = object.__new__(MemoryOperationsController)
        memory_ops.engine = engine
        memory_ops.integrity_filter = SimpleNamespace(
            check_contradiction=Mock(
                return_value={
                    "conflict": False,
                    "reason": "",
                    "impact_multiplier": 1.0,
                }
            )
        )
        memory_ops.slm_trainer = None
        persisted_stm_snapshots = []
        memory_ops.save_short_term_memory = lambda: persisted_stm_snapshots.append(
            list(engine.short_term_buffer)
        )
        engine.memory_ops = memory_ops
        engine.perception_ops = PerceptionController(engine)

        controller = InteractionController(engine)
        controller.sensory_preprocessor = SimpleNamespace(
            evaluate_input=Mock(
                return_value={
                    "vector": {
                        "valence": 0.0,
                        "arousal": 0.0,
                        "urgency": 0.0,
                    },
                    "summary": "neutral",
                }
            )
        )
        controller.reflex_gate = SimpleNamespace(
            evaluate_reflexes=Mock(return_value={"triggered": False})
        )
        controller.compressor = SimpleNamespace(compress=Mock(return_value=[]))

        with patch.object(Config, "USE_LOCAL_ONLY", False), patch.object(
            Config, "FORCE_LOCAL_COMMANDS", ["/local", "offline"]
        ), patch("random.random", return_value=1.0), patch(
            "builtins.print"
        ):
            local_result = controller.interaction_loop(hard_local_input)

            self.assertEqual(local_result["response"], "acknowledged")
            self.assertEqual(
                engine.short_term_buffer, ["User: prior public context"]
            )
            self.assertEqual(engine.memory.search_queries, [])
            self.assertEqual(engine.memory.added, [])
            self.assertEqual(engine.local_perception.calls, [])
            self.assertEqual(engine.ego.semantic_belief_reads, 0)
            # Private memory context has no read scope, including the
            # metadata-only path behind get_active_beliefs_local().
            self.assertEqual(engine.ego.local_belief_reads, 0)
            self.assertEqual(engine.ego.updated_states, [])
            self.assertEqual(engine.ego.social_need, 0.5)
            self.assertEqual(engine.ego.mood, 0.0)
            self.assertEqual(engine.ego.stress, 0.0)
            engine.world_graph.update_from_text.assert_not_called()
            engine.value_system.update_user_value.assert_not_called()
            engine.skills.execute.assert_not_called()
            engine._dump_mind_state.assert_not_called()
            self.assertEqual(persisted_stm_snapshots, [])
            local_calls = list(engine.llm.calls)
            self.assertTrue(local_calls)
            self.assertTrue(
                all(force_local for _, prompt, force_local in local_calls if sentinel in prompt)
            )

            cloud_result = controller.interaction_loop(public_input)

        self.assertEqual(cloud_result["response"], "acknowledged")
        cloud_calls = [call for call in engine.llm.calls if not call[2]]
        self.assertTrue(cloud_calls)
        self.assertTrue(all(sentinel not in prompt for _, prompt, _ in cloud_calls))
        self.assertEqual(engine.local_perception.calls, [public_input])
        self.assertTrue(
            all(sentinel not in text for text in engine.local_perception.calls)
        )
        self.assertTrue(engine.memory.search_queries)
        self.assertTrue(
            all(sentinel not in query for query in engine.memory.search_queries)
        )
        self.assertTrue(engine.memory.added)
        self.assertTrue(
            all(
                sentinel not in getattr(memory, "content", "")
                for memory in engine.memory.added
            )
        )
        graph_inputs = [call.args[0] for call in engine.world_graph.update_from_text.call_args_list]
        self.assertEqual(graph_inputs, [public_input])
        self.assertTrue(
            all(
                sentinel not in "\n".join(snapshot)
                for snapshot in persisted_stm_snapshots
            )
        )
        self.assertNotIn(sentinel.lower(), engine.ego.vocabulary)

        # Global local-only is a backend/no-network policy, not an ephemeral
        # privacy request. It must still update safe local conversational state.
        engine.llm.calls.clear()
        engine.local_perception.calls.clear()
        engine.world_graph.update_from_text.reset_mock()
        engine.skills.execute.reset_mock()
        local_only_input = "ordinary persistent local-only turn"
        with patch.object(Config, "USE_LOCAL_ONLY", True), patch.object(
            Config, "FORCE_LOCAL_COMMANDS", ["/local", "offline"]
        ), patch("random.random", return_value=1.0), patch("builtins.print"):
            local_only_result = controller.interaction_loop(local_only_input)

        self.assertEqual(local_only_result["response"], "acknowledged")
        self.assertIn(f"User: {local_only_input}", engine.short_term_buffer)
        self.assertTrue(engine.llm.calls)
        self.assertTrue(all(call[2] for call in engine.llm.calls))
        self.assertEqual(engine.local_perception.calls, [])
        engine.skills.execute.assert_not_called()
        engine.world_graph.update_from_text.assert_called_once()
        self.assertTrue(
            engine.world_graph.update_from_text.call_args.kwargs["force_local"]
        )


class InteractionPrecommitTransactionTests(unittest.TestCase):
    @staticmethod
    def _ego_snapshot(ego):
        return {
            "social_need": ego.social_need,
            "stress": ego.stress,
            "mood": ego.mood,
            "vocabulary": list(ego.vocabulary),
            "integrity": ego.integrity,
            "is_identity_crisis": ego.is_identity_crisis,
            "updated_states": list(ego.updated_states),
        }

    @staticmethod
    def _controller():
        engine = SimpleNamespace()
        engine.ego = _PrivacyEgo()
        engine.ego.stress = 0.1
        engine.ego.mood = 0.1
        engine.ego.integrity = 0.3
        engine.ego.is_identity_crisis = True
        engine.ego.vocabulary = ["stable"]
        engine.stm_lock = threading.Lock()
        engine.short_term_buffer = ["User: stable history"]

        recalled_memory = SimpleNamespace(
            id="recall-1",
            content="stable recalled memory",
            valence=0.2,
            arousal=0.1,
            strength=0.8,
            overlays=[],
        )
        recalled_memory.get_display_content = Mock(
            return_value="stable recalled memory"
        )
        recall_plan = SimpleNamespace(
            hits=(SimpleNamespace(memory=recalled_memory),)
        )
        engine.memory_ops = SimpleNamespace(
            build_recall_plan=Mock(return_value=recall_plan),
            apply_recall_effects=Mock(return_value=[recalled_memory]),
            _apply_fog_masking=lambda text: text,
            update_or_add_memory=Mock(),
            save_short_term_memory=Mock(),
            sleep=Mock(),
        )
        engine.memory = SimpleNamespace(get_all=Mock(return_value=[]))
        engine.local_perception = SimpleNamespace(
            mode="native",
            analyze=Mock(
                return_value={
                    "valence": 0.8,
                    "arousal": 0.9,
                    "confidence": 1.0,
                }
            ),
        )
        engine.perception_ops = SimpleNamespace(
            get_sensory_summary=Mock(return_value="neutral")
        )
        engine.world_graph = SimpleNamespace(
            query=Mock(return_value=[]), update_from_text=Mock()
        )
        engine.value_system = SimpleNamespace(
            get_moral_context=Mock(return_value=""),
            update_user_value=Mock(),
            update_user_values_batch=Mock(),
        )
        engine.skills = SimpleNamespace(
            get_prompt_instructions=Mock(return_value=""), execute=Mock()
        )
        engine.reader = SimpleNamespace(get_status=Mock(return_value="idle"))
        engine._dump_mind_state = Mock()
        engine.llm = SimpleNamespace(
            generate_text=Mock(return_value=("0.8", 0.0)),
            generate_json=Mock(
                return_value=(
                    {
                        "response": "committed reply",
                        "valence": 0.2,
                        "arousal": 0.3,
                        "importance": 0.5,
                        "type": "episodic",
                        "internal_monologue": "stable",
                        "thought": "stable",
                        "action": None,
                    },
                    0.0,
                )
            ),
        )

        controller = InteractionController(engine)
        controller.sensory_preprocessor = SimpleNamespace(
            evaluate_input=Mock(
                return_value={
                    "vector": {"arousal": 0.6, "urgency": 0.4},
                    "summary": "alert",
                }
            )
        )
        controller.reflex_gate = SimpleNamespace(
            evaluate_reflexes=Mock(return_value={"triggered": False})
        )
        controller.compressor = SimpleNamespace(
            compress=Mock(
                return_value=[
                    {"text": "stable recalled memory", "micro_tag": ""}
                ]
            )
        )
        return controller, engine, recall_plan

    def test_primary_generation_and_schema_failures_leave_all_state_unchanged(self):
        failures = (
            CloudTransportError("provider unavailable"),
            ({"response": "", "action": None}, 0.0),
        )
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                controller, engine, _ = self._controller()
                before_ego = self._ego_snapshot(engine.ego)
                before_stm = list(engine.short_term_buffer)
                if isinstance(failure, BaseException):
                    engine.llm.generate_json.side_effect = failure
                    expected_error = CloudTransportError
                else:
                    engine.llm.generate_json.return_value = failure
                    expected_error = InteractionOutputError

                with patch.object(Config, "USE_LOCAL_ONLY", False), patch.object(
                    Config, "FORCE_LOCAL_COMMANDS", ["/local"]
                ), patch("random.random", return_value=1.0), patch(
                    "builtins.print"
                ), self.assertRaises(expected_error):
                    controller.interaction_loop(
                        "bạn là aura, resilient transaction words"
                    )

                self.assertEqual(self._ego_snapshot(engine.ego), before_ego)
                self.assertEqual(engine.short_term_buffer, before_stm)
                engine.memory_ops.apply_recall_effects.assert_not_called()
                engine.memory_ops.update_or_add_memory.assert_not_called()
                engine.memory_ops.save_short_term_memory.assert_not_called()

    def test_cancellation_before_primary_commit_leaves_all_state_unchanged(self):
        controller, engine, _ = self._controller()
        before_ego = self._ego_snapshot(engine.ego)
        before_stm = list(engine.short_term_buffer)
        cancel_event = threading.Event()
        valid_output = engine.llm.generate_json.return_value

        def _cancel_during_primary(*_args, **_kwargs):
            cancel_event.set()
            return valid_output

        engine.llm.generate_json.side_effect = _cancel_during_primary
        with patch.object(Config, "USE_LOCAL_ONLY", False), patch.object(
            Config, "FORCE_LOCAL_COMMANDS", ["/local"]
        ), patch("random.random", return_value=1.0), patch(
            "builtins.print"
        ), self.assertRaises(InteractionCancelled) as caught:
            controller.interaction_loop(
                "bạn là aura, cancel this transaction",
                cancel_event=cancel_event,
                request_id="transaction-cancel-id",
            )

        self.assertEqual(caught.exception.request_id, "transaction-cancel-id")
        self.assertEqual(self._ego_snapshot(engine.ego), before_ego)
        self.assertEqual(engine.short_term_buffer, before_stm)
        engine.memory_ops.apply_recall_effects.assert_not_called()
        engine.memory_ops.update_or_add_memory.assert_not_called()
        engine.memory_ops.save_short_term_memory.assert_not_called()

    def test_postcommit_recall_and_logger_failure_cannot_hide_reply(self):
        controller, engine, recall_plan = self._controller()
        engine.llm.generate_text.side_effect = [("0.8", 0.0), ("[]", 0.0)]
        engine.memory_ops.apply_recall_effects.side_effect = RuntimeError(
            "private storage detail"
        )

        with patch.object(Config, "USE_LOCAL_ONLY", False), patch.object(
            Config, "FORCE_LOCAL_COMMANDS", ["/local"]
        ), patch("random.random", return_value=1.0), patch(
            "builtins.print"
        ), patch(
            "core.logger.get_logger", side_effect=RuntimeError("logger offline")
        ):
            result = controller.interaction_loop("transaction enrichment")

        self.assertEqual(result["response"], "committed reply")
        engine.memory_ops.apply_recall_effects.assert_called_once_with(recall_plan)
        engine.memory_ops.update_or_add_memory.assert_called_once()
        engine.memory_ops.save_short_term_memory.assert_called_once()
        self.assertIn("User: transaction enrichment", engine.short_term_buffer)
        primary_prompt = engine.llm.generate_json.call_args.args[0]
        self.assertIn("stable recalled memory", primary_prompt)

    def test_postcommit_baseexception_cannot_hide_reply(self):
        controller, engine, _ = self._controller()
        engine.llm.generate_text.side_effect = [("0.2", 0.0), ("[]", 0.0)]
        engine.ego.update_state = Mock(side_effect=KeyboardInterrupt())

        with patch.object(Config, "USE_LOCAL_ONLY", False), patch.object(
            Config, "FORCE_LOCAL_COMMANDS", ["/local"]
        ), patch("random.random", return_value=1.0), patch(
            "builtins.print"
        ), patch(
            "core.logger.get_logger", side_effect=KeyboardInterrupt()
        ):
            result = controller.interaction_loop("baseexception enrichment")

        self.assertEqual(result["response"], "committed reply")
        engine.memory_ops.update_or_add_memory.assert_called_once()
        engine.memory_ops.save_short_term_memory.assert_called_once()

    def test_postcommit_input_plan_never_overwrites_committed_tool_state(self):
        controller, engine, _ = self._controller()
        engine.llm.generate_text.side_effect = [("0.2", 0.0), ("[]", 0.0)]
        engine.llm.generate_json.return_value = (
            {
                "response": "",
                "action": "stateful_tool|payload",
                "valence": 0.0,
                "arousal": 0.1,
                "importance": 0.5,
                "type": "episodic",
                "internal_monologue": "use tool",
                "thought": "use tool",
            },
            0.0,
        )

        def _commit_tool_state(*_args, **_kwargs):
            engine.ego.stress = 0.91
            return "tool committed"

        engine.skills.execute.side_effect = _commit_tool_state
        with patch.object(Config, "USE_LOCAL_ONLY", False), patch.object(
            Config, "FORCE_LOCAL_COMMANDS", ["/local"]
        ), patch("random.random", return_value=1.0), patch("builtins.print"):
            result = controller.interaction_loop("stateful tool transaction")

        self.assertEqual(result["response"], "tool committed")
        self.assertEqual(engine.ego.stress, 0.91)

    def test_tool_output_render_failure_cannot_turn_side_effect_into_retry(self):
        controller, engine, _ = self._controller()
        engine.llm.generate_text.side_effect = [("0.2", 0.0), ("[]", 0.0)]
        engine.llm.generate_json.return_value = (
            {
                "response": "",
                "action": "stateful_tool|payload",
                "valence": 0.0,
                "arousal": 0.1,
                "importance": 0.5,
                "type": "episodic",
                "internal_monologue": "use tool",
                "thought": "use tool",
            },
            0.0,
        )

        class UnrenderableReceipt:
            def __str__(self):
                raise RuntimeError("receipt rendering failed")

        committed = []

        def commit_tool(*_args, **_kwargs):
            committed.append("once")
            return UnrenderableReceipt()

        engine.skills.execute.side_effect = commit_tool
        with patch.object(Config, "USE_LOCAL_ONLY", False), patch.object(
            Config, "FORCE_LOCAL_COMMANDS", ["/local"]
        ), patch("random.random", return_value=1.0), patch("builtins.print"):
            result = controller.interaction_loop("stateful receipt transaction")

        self.assertEqual(committed, ["once"])
        self.assertEqual(
            result["response"], "Đã thực thi hành động: stateful_tool"
        )

    def test_tool_rechecks_cancellation_immediately_before_execute(self):
        controller, engine, _ = self._controller()
        engine.llm.generate_text.side_effect = [("0.2", 0.0)]
        engine.llm.generate_json.return_value = (
            {
                "response": "",
                "action": "stateful_tool|payload",
                "valence": 0.0,
                "arousal": 0.1,
                "importance": 0.5,
                "type": "episodic",
                "internal_monologue": "use tool",
                "thought": "use tool",
            },
            0.0,
        )
        cancel_event = threading.Event()

        def cancel_on_tool_notice(*args, **_kwargs):
            if args and "Aura sử dụng kỹ năng" in str(args[0]):
                cancel_event.set()

        with patch.object(Config, "USE_LOCAL_ONLY", False), patch.object(
            Config, "FORCE_LOCAL_COMMANDS", ["/local"]
        ), patch("random.random", return_value=1.0), patch(
            "builtins.print", side_effect=cancel_on_tool_notice
        ), self.assertRaises(InteractionCancelled) as caught:
            controller.interaction_loop(
                "cancel before tool",
                cancel_event=cancel_event,
                request_id="tool-cancel-id",
            )

        self.assertEqual(caught.exception.request_id, "tool-cancel-id")
        engine.skills.execute.assert_not_called()

    def test_malformed_second_value_item_causes_zero_value_mutation(self):
        controller, engine, _ = self._controller()
        engine.llm.generate_text.side_effect = [
            ("0.2", 0.0),
            (
                '[{"value":"Honesty","sentiment":0.8},'
                '{"value":"Broken","sentiment":true}]',
                0.0,
            ),
        ]

        with patch.object(Config, "USE_LOCAL_ONLY", False), patch.object(
            Config, "FORCE_LOCAL_COMMANDS", ["/local"]
        ), patch("random.random", return_value=1.0), patch("builtins.print"):
            result = controller.interaction_loop("value extraction transaction")

        self.assertEqual(result["response"], "committed reply")
        engine.value_system.update_user_value.assert_not_called()
        engine.value_system.update_user_values_batch.assert_not_called()

    def test_low_signal_invalid_value_is_rejected_before_material_filter(self):
        controller, engine, _ = self._controller()
        engine.llm.generate_text.side_effect = [
            ("0.2", 0.0),
            (
                '[{"value":"Honesty","sentiment":0.8},'
                '{"value":"Broken\\nName","sentiment":0.1}]',
                0.0,
            ),
        ]

        with patch.object(Config, "USE_LOCAL_ONLY", False), patch.object(
            Config, "FORCE_LOCAL_COMMANDS", ["/local"]
        ), patch("random.random", return_value=1.0), patch("builtins.print"):
            result = controller.interaction_loop("value control transaction")

        self.assertEqual(result["response"], "committed reply")
        engine.value_system.update_user_value.assert_not_called()
        engine.value_system.update_user_values_batch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
