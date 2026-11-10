import copy
import os
import time
import math
import threading
import re
import uuid
import concurrent.futures
from dataclasses import dataclass
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, List
from colorama import Fore, Style
from components.llm import LLM
from components.embedder import Embedder
from components.reader import BackgroundReader
from core.memory import MemoryManager
from core.operation_ledger import OperationLedger
from core.self_model import SelfModel
from core.logger import get_logger
from config import Config
from .memory_ops import MemoryOperationsController
from .interaction import InteractionController
from .interaction_actor import (
    InteractionActor,
    InteractionActorClosed,
    InteractionCancelled,
    InteractionRequest,
)
from .autonomous import AutonomousController
from .perception import PerceptionController
from .slm_core import SLMCore
from core.agent_state import StateMachine, AgentState
from core.event_journal import (
    EventJournal,
    JournalContext,
    RotatingEventJournal,
    activate_journal_context,
    current_journal_context,
    detach_current_event_head,
    record_current_event,
    reset_journal_context,
)
from core.memory_context import (
    interaction_memory_context,
    maintenance_memory_context,
    memory_context_scope,
)
from core.state_projection import (
    capture_state_projection,
    diff_projection,
    projection_hash,
)

logger = get_logger("cognitive_engine")


# Explicitly scoped to RAM fields mutated by the cognitive tick's biological
# phase (including SelfModel helpers called by that phase).  Keeping this list
# narrow avoids copying identity text or memory-manager references while still
# making the biological transition reversible at a phase boundary.
_TICK_BIOLOGY_FIELDS = (
    "mood",
    "stress",
    "fatigue",
    "curiosity",
    "social_need",
    "integrity",
    "is_identity_crisis",
    "energy",
    "atp_level",
    "fatigue_mild",
    "fatigue_severe",
    "fatigue_critical",
    "depression_mild",
    "depression_severe",
    "depression_critical",
    "mania_mild",
    "mania_severe",
    "stress_mild",
    "stress_severe",
    "stress_critical",
    "dopamine_receptors",
    "dopamine_level",
    "dopamine_baseline",
    "reward_expectations",
    "current_intimacy",
    "relational_friction",
    "boredom",
    "resilience",
    "sleep_debt",
    "days_without_sleep",
    "_sleep_warning_cooldown",
    "_last_circadian_time",
)


_JOURNAL_IDENTIFIER_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,191}$", re.ASCII
)
_JOURNAL_SOURCES = frozenset(
    {
        "unknown",
        "cli",
        "web",
        "discord",
        "autonomous",
        "system",
        "dashboard",
        "test",
        "sync",
        "async",
    }
)
_JOURNAL_INIT_LOCK = threading.Lock()


@dataclass(slots=True)
class _JournalRequestState:
    context: JournalContext
    operation: str
    accepted_event_id: str
    # Concrete immutable run selected atomically with interaction.accepted.
    # Never route continuation events back through the rotating facade.
    journal: EventJournal | None = None
    head_event_id: str | None = None
    accepted_recorded: bool = False
    context_token: Any = None
    baseline: dict[str, Any] | None = None


class CognitiveEngine:
    def __init__(
        self,
        *,
        llm=None,
        embedder=None,
        memory=None,
        ego=None,
        operation_ledger=None,
    ):
        self._owns_memory = memory is None
        # Match MemoryManager DI ownership: an injected ledger remains owned
        # by its caller, while the production ledger follows engine lifetime.
        self._owns_operation_ledger = operation_ledger is None
        self._operation_ledger_close_attempted = False
        self._operation_ledger_close_result = None
        try:
            self._initialize(
                llm=llm,
                embedder=embedder,
                memory=memory,
                ego=ego,
                operation_ledger=operation_ledger,
            )
        except BaseException:
            # A partially initialized engine has no public shutdown path.
            # Never release writer ownership while a partially-created worker
            # could still mutate memory.
            quiesced = self._quiesce_failed_initialization()
            owned_memory = getattr(self, "memory", None)
            close_memory = getattr(owned_memory, "close", None)
            if self._owns_memory and quiesced and callable(close_memory):
                try:
                    close_memory()
                except Exception:
                    logger.error(
                        "Memory cleanup after engine initialization failed",
                        exc_info=True,
                    )
            elif self._owns_memory and not quiesced:
                logger.critical(
                    "Partial engine worker survived initialization failure; "
                    "retaining the process writer lease"
                )
            raise

    def _quiesce_failed_initialization(self) -> bool:
        clean = True

        # Stop new admissions before waiting for any worker that may already
        # own the runtime gate. This also protects against `self` having been
        # exposed through the global skill registry during late initialization.
        state_machine = getattr(self, "state_machine", None)
        if (
            state_machine is not None
            and state_machine.state != AgentState.SHUTDOWN
        ):
            try:
                clean = state_machine.transition(AgentState.SHUTDOWN) and clean
            except BaseException:
                clean = False
                logger.error(
                    "State cleanup after initialization failed",
                    exc_info=True,
                )

        interaction_actor = getattr(self, "interaction_actor", None)
        actor_shutdown = getattr(interaction_actor, "shutdown", None)
        if callable(actor_shutdown):
            try:
                actor_result = actor_shutdown(
                    drain=False,
                    timeout=Config.INTERACTION_SHUTDOWN_TIMEOUT_SECONDS,
                )
                clean = (actor_result is not False) and clean
            except BaseException:
                clean = False
                logger.error(
                    "Interaction actor cleanup after initialization failed",
                    exc_info=True,
                )

        autonomous = getattr(self, "autonomous", None)
        autonomous_stop = getattr(autonomous, "stop", None)
        if callable(autonomous_stop):
            try:
                autonomous_result = autonomous_stop(
                    timeout=Config.AUTONOMOUS_SHUTDOWN_TIMEOUT_SECONDS,
                )
                clean = (autonomous_result is not False) and clean
            except BaseException:
                clean = False
                logger.error(
                    "Autonomous cleanup after initialization failed",
                    exc_info=True,
                )

        reader = getattr(self, "reader", None)
        reader_stop = getattr(reader, "stop", None)
        if callable(reader_stop):
            try:
                reader_stop()
            except BaseException:
                clean = False
                logger.error(
                    "Reader cleanup after initialization failed",
                    exc_info=True,
                )

        # The ledger may contain immutable plans already visible to workers.
        # Keep it open if a partial tick still owns the mutation gate.
        gate = getattr(self, "_runtime_mutation_gate", None)
        gate_acquired = clean and (
            gate is None
            or gate.acquire(timeout=Config.INTERACTION_SHUTDOWN_TIMEOUT_SECONDS)
        )
        if clean and not gate_acquired:
            clean = False
        if gate_acquired:
            try:
                if not self._close_owned_operation_ledger_once():
                    clean = False
            finally:
                if gate is not None:
                    gate.release()

        return clean

    def _close_owned_operation_ledger_once(self) -> bool:
        """Close the engine-owned ledger at most once after quiescence."""
        if not getattr(self, "_owns_operation_ledger", False):
            return True
        ledger = getattr(self, "operation_ledger", None)
        if ledger is None:
            return True
        if getattr(self, "_operation_ledger_close_attempted", False):
            return getattr(self, "_operation_ledger_close_result", False) is True

        # Set before calling user-visible cleanup. A close implementation that
        # raises must not be invoked a second time by a repeated shutdown.
        self._operation_ledger_close_attempted = True
        self._operation_ledger_close_result = False
        close_ledger = getattr(ledger, "close", None)
        if not callable(close_ledger):
            logger.error("Owned operation ledger has no close method")
            return False
        try:
            close_ledger()
            self._operation_ledger_close_result = True
            return True
        except BaseException:
            logger.error("Operation ledger cleanup failed", exc_info=True)
            return False

    def _initialize(
        self,
        *,
        llm=None,
        embedder=None,
        memory=None,
        ego=None,
        operation_ledger=None,
    ):
        """
        Khởi tạo CognitiveEngine với hỗ trợ Dependency Injection (DI).
        Khi chạy thật:    engine = CognitiveEngine()
        Khi viết test:    engine = CognitiveEngine(memory=FakeMemory(), llm=FakeLLM())
        """
        self.embedder = embedder if embedder is not None else Embedder()
        self.memory = (
            memory if memory is not None else MemoryManager(self.embedder)
        )
        self.ego = (
            ego if ego is not None else SelfModel(memory_manager=self.memory)
        )
        self.llm = llm if llm is not None else LLM(ego=self.ego)

        # Each subsystem owns its own lock. STM is independent from vector
        # storage so console/dashboard traffic cannot hold the DB lock.
        self.short_term_buffer: List[str] = []
        self.stm_lock = threading.Lock()
        from core.engine.lingering_thought import LingeringThought

        self.lingering_thought = LingeringThought()
        from core.engine.life_log import LifeLog

        self.life_log = LifeLog()
        self.stm_file_path = Config.STM_FILE  # Phase 15: dung Config thay hardcode
        self.last_interaction_time = time.time()
        
        # Phase 12: Áp dụng StateMachine thực sự.
        self.state_machine = StateMachine()
        self._state_duration_checkpoint = self.state_machine.duration_totals()
        self._runtime_mutation_gate = threading.Lock()
        self._interaction_state_lock = threading.Lock()
        self._interaction_state_owner: str | None = None
        self._shutdown_lock = threading.Lock()
        self._shutdown_complete = False
        self._shutdown_result = None
        self._journal_tracking_lock = threading.Lock()
        self._journal_requests: dict[int, _JournalRequestState] = {}
        self.event_journal = None
        if Config.EVENT_JOURNAL_ENABLED:
            try:
                self.event_journal = RotatingEventJournal(
                    Config.EVENT_JOURNAL_DIR,
                    max_events=Config.EVENT_JOURNAL_MAX_EVENTS_PER_RUN,
                    max_event_bytes=Config.EVENT_JOURNAL_MAX_EVENT_BYTES,
                    lock_timeout_seconds=(
                        Config.EVENT_JOURNAL_LOCK_TIMEOUT_SECONDS
                    ),
                    auth_key=Config.EVENT_JOURNAL_AUTH_KEY,
                )
                self.event_journal.append_safe(
                    "journal.run_started",
                    {"format": "atomic-json-v1"},
                    context=JournalContext(source="system"),
                    outcome="started",
                )
            except Exception:
                # Observability is fail-open: a disk or configuration problem
                # must never prevent the cognitive runtime from starting.
                self.event_journal = None
                logger.warning("Event journal initialization failed", exc_info=True)

        from core.tools import get_skill_registry
        self.skills = get_skill_registry()
        self.skills.engine = self  # Phase 2: Bridge tools to engine
        self.skills.load()  # Phase 6: Nạp độ thông thạo từ ổ cứng
        self.reader = BackgroundReader(self.llm)

        from core.world_graph import WorldGraph
        self.world_graph = WorldGraph(Config.WORLD_GRAPH_FILE)

        from core.value_system import ValueSystem
        self.value_system = ValueSystem(Config.VALUES_FILE)

        from core.prospective_memory import ProspectiveMemory
        self.prospective = ProspectiveMemory(Config.PROSPECTIVE_MEMORY_FILE)
        from core.relationship import InsideJokes
        self.inside_jokes = InsideJokes(Config.INSIDE_JOKES_FILE)

        from core.local_perception import LocalPerception
        self.local_perception = LocalPerception()

        # Fail closed: durable operation recovery must never silently fall
        # back to an untracked MemoryOperationsController. Construction is
        # intentionally before that controller can observe the engine.
        self.operation_ledger = (
            operation_ledger
            if operation_ledger is not None
            else OperationLedger()
        )
        self.memory_ops = MemoryOperationsController(self)
        self.perception_ops = PerceptionController(self)
        self.interaction = InteractionController(self)
        self.interaction_actor = InteractionActor(
            self._run_interaction_request,
            capacity=Config.INTERACTION_QUEUE_MAX,
            before_request=self._before_interaction_request,
            after_request=self._after_interaction_request,
        )
        self.autonomous = AutonomousController(self)
        self.slm = SLMCore()

        if not os.path.exists("outputs"):
            os.makedirs("outputs")

        # B4: Public methods own their locks. Initialization is single-threaded,
        # and init_core_semantics may acquire the memory lock.
        self.ego.load_state()
        self.ego.init_core_semantics()
        logger.info("CognitiveEngine initialized. Ego state loaded and core semantics seeded.")

        self.memory_ops.load_short_term_memory()

    @staticmethod
    def _journal_operation(request: InteractionRequest) -> str:
        payload = request.payload
        if isinstance(payload, Mapping) and payload.get("operation") == "sleep":
            return "sleep"
        return "interaction"

    @staticmethod
    def _journal_identifier(request_id: str) -> str:
        value = str(request_id or "")
        if _JOURNAL_IDENTIFIER_RE.fullmatch(value):
            return value
        # Actor request IDs are intentionally more permissive than journal
        # identifiers. Never derive persisted metadata from an unsafe value.
        return uuid.uuid4().hex

    @staticmethod
    def _journal_source(source: str) -> str:
        normalized = str(source or "unknown").lower()
        return normalized if normalized in _JOURNAL_SOURCES else "unknown"

    def _journal_tracking_parts(self):
        """Return lazily initialized tracking state for small test doubles."""
        lock = getattr(self, "_journal_tracking_lock", None)
        states = getattr(self, "_journal_requests", None)
        if lock is not None and states is not None:
            return lock, states
        with _JOURNAL_INIT_LOCK:
            lock = getattr(self, "_journal_tracking_lock", None)
            if lock is None:
                lock = threading.Lock()
                self._journal_tracking_lock = lock
            states = getattr(self, "_journal_requests", None)
            if states is None:
                states = {}
                self._journal_requests = states
        return lock, states

    def _ensure_journal_accepted(
        self, request: InteractionRequest
    ) -> _JournalRequestState | None:
        """Create the durable acceptance head once, despite submit/start races."""
        try:
            return self._ensure_journal_accepted_unsafe(request)
        except Exception:
            # Admission observability is never allowed to change actor
            # acceptance or the result visible to the producer.
            logger.warning("Unable to record interaction acceptance", exc_info=True)
            return None

    def _ensure_journal_accepted_unsafe(
        self, request: InteractionRequest
    ) -> _JournalRequestState | None:
        journal = getattr(self, "event_journal", None)
        lock, states = self._journal_tracking_parts()
        key = id(request)
        with lock:
            state = states.get(key)
            if state is not None and state.accepted_recorded:
                return state
            if journal is None:
                return None
            if state is None:
                payload = request.payload
                private_ephemeral = bool(
                    isinstance(payload, Mapping)
                    and payload.get("private_ephemeral", False)
                )
                identifier = (
                    uuid.uuid4().hex
                    if private_ephemeral
                    else self._journal_identifier(request.request_id)
                )
                state = _JournalRequestState(
                    context=JournalContext(
                        correlation_id=identifier,
                        trace_id=identifier,
                        request_id=identifier,
                        source=self._journal_source(request.source),
                        private_ephemeral=private_ephemeral,
                    ),
                    operation=self._journal_operation(request),
                    accepted_event_id=uuid.uuid4().hex,
                )
                states[key] = state
            if not state.accepted_recorded:
                pinned_append = getattr(journal, "append_pinned_safe", None)
                if callable(pinned_append):
                    pinned = pinned_append(
                        "interaction.accepted",
                        {"operation": state.operation},
                        context=state.context,
                        outcome="accepted",
                        event_id=state.accepted_event_id,
                    )
                    if pinned is None:
                        event = None
                        concrete_journal = None
                    else:
                        concrete_journal, event = pinned
                else:
                    event = journal.append_safe(
                        "interaction.accepted",
                        {"operation": state.operation},
                        context=state.context,
                        outcome="accepted",
                        event_id=state.accepted_event_id,
                    )
                    concrete_journal = journal
                if event is not None:
                    state.accepted_recorded = True
                    state.journal = concrete_journal
                    state.head_event_id = event.event_id
            return state if state.accepted_recorded else None

    def _activate_request_journal(self, request: InteractionRequest) -> None:
        state = self._ensure_journal_accepted(request)
        journal = None if state is None else state.journal
        if state is None or journal is None:
            return
        try:
            token = activate_journal_context(
                journal,
                state.context,
                causation_id=state.head_event_id,
            )
            lock, states = self._journal_tracking_parts()
            with lock:
                current = states.get(id(request))
                if current is not None:
                    current.context_token = token
            queue_wait_ms = max(
                0.0, (time.monotonic() - request.submitted_at) * 1000.0
            )
            record_current_event(
                "interaction.started",
                {
                    "operation": state.operation,
                    "queue_wait_ms": round(queue_wait_ms, 3),
                },
                outcome="started",
            )
            self._update_request_journal_head(request)
        except Exception:
            logger.warning("Unable to activate interaction journal", exc_info=True)

    def _update_request_journal_head(self, request: InteractionRequest) -> None:
        try:
            head = detach_current_event_head()
            lock, states = self._journal_tracking_parts()
            with lock:
                state = states.get(id(request))
                if state is not None:
                    state.head_event_id = head
        except Exception:
            logger.warning("Unable to update interaction journal head", exc_info=True)

    def _capture_request_baseline(self, request: InteractionRequest) -> None:
        try:
            lock, states = self._journal_tracking_parts()
            with lock:
                state = states.get(id(request))
                if state is None or state.journal is None:
                    return
            baseline = capture_state_projection(self)
            # Hash now so non-finite or otherwise non-canonical values fail
            # before they can affect request execution or cleanup.
            projection_hash(baseline)
            with lock:
                state = states.get(id(request))
                if state is not None:
                    state.baseline = baseline
        except Exception:
            logger.warning("Unable to capture interaction baseline", exc_info=True)

    def _record_request_state_delta(self, request: InteractionRequest) -> None:
        try:
            lock, states = self._journal_tracking_parts()
            with lock:
                state = states.get(id(request))
                if state is None or state.journal is None:
                    return
                baseline = None if state is None else state.baseline
            if baseline is None:
                return
            after = capture_state_projection(self)
            before_hash = projection_hash(baseline)
            after_hash = projection_hash(after)
            snapshot_event = record_current_event(
                "state.snapshot",
                {
                    "projection": baseline,
                    "projection_hash": before_hash,
                },
                outcome="succeeded",
            )
            if snapshot_event is not None:
                record_current_event(
                    "state.delta",
                    {
                        "before_hash": before_hash,
                        "after_hash": after_hash,
                        "patch": diff_projection(baseline, after),
                    },
                    outcome="succeeded",
                )
            self._update_request_journal_head(request)
        except Exception:
            logger.warning("Unable to record interaction state delta", exc_info=True)

    def _reset_request_journal(self, request: InteractionRequest) -> None:
        token = None
        try:
            self._update_request_journal_head(request)
            lock, states = self._journal_tracking_parts()
            with lock:
                state = states.get(id(request))
                if state is not None:
                    token = state.context_token
                    state.context_token = None
        finally:
            if token is not None:
                try:
                    reset_journal_context(token)
                except Exception:
                    logger.warning(
                        "Unable to reset interaction journal context", exc_info=True
                    )

    def _finish_request_journal(self, request: InteractionRequest, future) -> None:
        """Record the actor's final Future arbitration, never response content."""
        try:
            # A transient failure at submission may recover before terminal
            # arbitration. Retry the stable, idempotent acceptance event first.
            accepted = self._ensure_journal_accepted(request)
            lock, states = self._journal_tracking_parts()
            with lock:
                state = states.pop(id(request), None)
            if state is None or accepted is None or state.journal is None:
                return
            journal = state.journal

            result = None
            error: BaseException | None = None
            if future.cancelled():
                outcome = "cancelled"
                error = concurrent.futures.CancelledError()
            else:
                error = future.exception()
                if error is None:
                    result = future.result()
                    outcome = "succeeded"
                elif isinstance(error, InteractionCancelled):
                    outcome = "cancelled"
                else:
                    outcome = "failed"

            if isinstance(result, Mapping):
                response_present = bool(result.get("response"))
            else:
                response_present = result is not None
            payload: dict[str, Any] = {
                "operation": state.operation,
                "duration_ms": round(
                    max(0.0, time.monotonic() - request.submitted_at) * 1000.0,
                    3,
                ),
                "response_present": response_present,
            }
            if error is not None:
                payload["error_type"] = type(error).__name__
            journal.append_safe(
                "interaction.finished",
                payload,
                context=state.context,
                outcome=outcome,
                causation_id=state.head_event_id,
            )
        except BaseException:
            # A Future callback must be incapable of altering or obscuring the
            # result already selected by InteractionActor.
            logger.warning("Unable to finish interaction journal", exc_info=True)

    def submit_interaction(
        self,
        user_input: str,
        *,
        source: str = "unknown",
        is_deep_mode: bool = False,
        model_override: str | None = None,
        request_id: str | None = None,
        privacy_input: str | None = None,
    ):
        """Submit one bounded, actor-owned interaction without blocking."""
        if not isinstance(user_input, str):
            raise TypeError("user_input must be a string")
        if not user_input.strip():
            raise ValueError("user_input must not be empty")
        raw_privacy_input = user_input if privacy_input is None else privacy_input
        if not isinstance(raw_privacy_input, str):
            raise TypeError("privacy_input must be a string")
        # A transport may provide the undecorated input so a prefix remains
        # detectable after adding routing metadata (for example Discord's
        # stable owner ID). It may only strengthen privacy, never downgrade a
        # private command that is already present in the actual model input.
        private_ephemeral = (
            self.interaction._is_private_ephemeral_input(user_input)
            or self.interaction._is_private_ephemeral_input(raw_privacy_input)
        )
        force_local = (
            private_ephemeral
            or self.interaction._requires_local_backend(user_input)
            or self.interaction._requires_local_backend(raw_privacy_input)
        )
        ticket = self.interaction_actor.submit(
            MappingProxyType({
                "user_input": user_input,
                "is_deep_mode": bool(is_deep_mode),
                "model_override": model_override,
                "force_local": force_local,
                "private_ephemeral": private_ephemeral,
            }),
            source=source,
            request_id=request_id,
        )
        self._ensure_journal_accepted(ticket.request)
        ticket.future.add_done_callback(
            lambda future, request=ticket.request: self._finish_request_journal(
                request, future
            )
        )
        return ticket

    def submit_sleep(self, *, source: str = "unknown", request_id: str | None = None):
        """Serialize an explicit sleep command with all other mutations."""
        ticket = self.interaction_actor.submit(
            MappingProxyType({"operation": "sleep"}),
            source=source,
            request_id=request_id,
        )
        self._ensure_journal_accepted(ticket.request)
        ticket.future.add_done_callback(
            lambda future, request=ticket.request: self._finish_request_journal(
                request, future
            )
        )
        return ticket

    def _run_interaction_request(self, request: InteractionRequest):
        payload = request.payload
        if not isinstance(payload, Mapping):
            raise TypeError("interaction payload must be a mapping")
        active_journal = current_journal_context()
        source_event_id = (
            active_journal.last_event_id
            if active_journal is not None
            else request.request_id
        )
        if payload.get("operation") == "sleep":
            with memory_context_scope(
                maintenance_memory_context(
                    origin_kind="sleep",
                    origin_source=request.source,
                    source_event_id=source_event_id,
                )
            ):
                return self.memory_ops.sleep()

        memory_context = interaction_memory_context(
            source=request.source,
            request_id=source_event_id,
            private_ephemeral=bool(payload.get("private_ephemeral", False)),
            local_only=bool(payload.get("force_local", False)),
        )
        with memory_context_scope(memory_context):
            return self.interaction.interaction_loop(
                payload["user_input"],
                is_deep_mode=payload.get("is_deep_mode", False),
                model_override=payload.get("model_override"),
                cancel_event=request.cancel_event,
                force_local=payload.get("force_local", False),
                private_ephemeral=payload.get("private_ephemeral", False),
                request_id=request.request_id,
            )

    def _before_interaction_request(self, request: InteractionRequest) -> None:
        """Wait boundedly for autonomous work, then claim THINKING state."""
        self._activate_request_journal(request)
        deadline = time.monotonic() + Config.INTERACTION_STATE_WAIT_SECONDS
        desired_state = (
            AgentState.SLEEPING
            if isinstance(request.payload, Mapping)
            and request.payload.get("operation") == "sleep"
            else AgentState.THINKING
        )
        while True:
            request.raise_if_cancelled()
            state = self.state_machine.state
            if state == AgentState.SHUTDOWN:
                raise InteractionActorClosed("cognitive engine is shut down")
            remaining = deadline - time.monotonic()
            if remaining <= 0.0:
                raise TimeoutError(
                    f"engine remained busy in state {state.name} while interaction waited"
                )
            if state == AgentState.IDLE and self._runtime_mutation_gate.acquire(
                timeout=min(0.05, remaining)
            ):
                self._capture_request_baseline(request)
                if (
                    self.state_machine.state == AgentState.IDLE
                    and self.state_machine.transition(desired_state)
                ):
                    with self._interaction_state_lock:
                        self._interaction_state_owner = request.request_id
                    self._update_request_journal_head(request)
                    return
                self._runtime_mutation_gate.release()
            request.cancel_event.wait(0.05)

    def _after_interaction_request(
        self, request: InteractionRequest, error: BaseException | None
    ) -> None:
        # A failed/cancelled before-hook must never release THINKING state
        # owned by an autonomous action. Only the request that claimed it may
        # transition it back to IDLE.
        with self._interaction_state_lock:
            owns_state = self._interaction_state_owner == request.request_id
            if owns_state:
                self._interaction_state_owner = None
        try:
            if owns_state:
                if self.state_machine.state in (
                    AgentState.THINKING,
                    AgentState.SLEEPING,
                ):
                    self.state_machine.transition(AgentState.IDLE)
                self._record_request_state_delta(request)
        finally:
            self._reset_request_journal(request)
            if owns_state:
                self._runtime_mutation_gate.release()

    def cognitive_tick(self, dt: float = 30.0, cancel_event=None):
        """Run a tick only when no actor-owned mutation is in progress.

        Returning False tells the cadence controller to retain accumulated dt;
        the next admitted biological transaction therefore catches up instead
        of losing time. Once biology commits, later maintenance failure still
        consumes the interval so the biological effects are never replayed.
        """
        gate = getattr(self, "_runtime_mutation_gate", None)
        if gate is not None and not gate.acquire(blocking=False):
            return False
        journal_token = None
        tick_baseline = None
        tick_started_at = time.monotonic()
        tick_error_type: str | None = None
        tick_outcome = "skipped"
        tick_execution_status: dict[str, str] = {}
        duration_snapshot = None
        try:
            elapsed_seconds = float(dt)
        except (TypeError, ValueError):
            elapsed_seconds = 0.0
        if not math.isfinite(elapsed_seconds) or elapsed_seconds < 0.0:
            elapsed_seconds = 0.0
        try:
            state_machine = getattr(self, "state_machine", None)
            if (
                state_machine is not None
                and state_machine.state == AgentState.SHUTDOWN
            ):
                return False

            journal = getattr(self, "event_journal", None)
            if journal is not None:
                try:
                    identifier = f"tick:{uuid.uuid4().hex}"
                    context = JournalContext(
                        correlation_id=identifier,
                        trace_id=identifier,
                        source="autonomous",
                    )
                    pinned_append = getattr(journal, "append_pinned_safe", None)
                    if callable(pinned_append):
                        pinned = pinned_append(
                            "cognitive_tick.started",
                            {"elapsed_seconds": elapsed_seconds},
                            context=context,
                            outcome="started",
                        )
                        if pinned is None:
                            tick_journal = None
                            started_event = None
                        else:
                            tick_journal, started_event = pinned
                    else:
                        tick_journal = journal
                        started_event = journal.append_safe(
                            "cognitive_tick.started",
                            {"elapsed_seconds": elapsed_seconds},
                            context=context,
                            outcome="started",
                        )
                    if started_event is not None:
                        journal_token = activate_journal_context(
                            tick_journal,
                            context,
                            causation_id=started_event.event_id,
                        )
                        try:
                            tick_baseline = capture_state_projection(self)
                            projection_hash(tick_baseline)
                        except Exception:
                            tick_baseline = None
                            logger.warning(
                                "Unable to capture cognitive tick baseline",
                                exc_info=True,
                            )
                except Exception:
                    logger.warning("Unable to start cognitive tick journal", exc_info=True)

            state_durations, duration_snapshot = self._state_duration_mix(dt)
            result = self._cognitive_tick_owned(
                dt,
                cancel_event,
                state_durations=state_durations,
                execution_status=tick_execution_status,
            )
            biology_status = tick_execution_status.get("biology_status")
            cadence_consumed = result is not False and biology_status not in {
                "not_started",
                "rolled_back",
            }
            if duration_snapshot is not None and cadence_consumed:
                self._state_duration_checkpoint = duration_snapshot
            tick_error_type = tick_execution_status.get("error_type")
            if tick_error_type is not None:
                tick_outcome = "failed"
            elif tick_execution_status.get("outcome") == "cancelled":
                tick_outcome = "cancelled"
            else:
                tick_outcome = "succeeded" if result is not False else "skipped"
            return result
        except BaseException as exc:
            # A BaseException after the biological phase committed must not
            # make the cadence replay that already-applied interval.
            if (
                duration_snapshot is not None
                and tick_execution_status.get("biology_status") == "committed"
            ):
                self._state_duration_checkpoint = duration_snapshot
            tick_error_type = type(exc).__name__
            tick_outcome = "failed"
            raise
        finally:
            if journal_token is not None:
                try:
                    if tick_baseline is not None:
                        try:
                            tick_after = capture_state_projection(self)
                            before_hash = projection_hash(tick_baseline)
                            after_hash = projection_hash(tick_after)
                            snapshot_event = record_current_event(
                                "state.snapshot",
                                {
                                    "projection": tick_baseline,
                                    "projection_hash": before_hash,
                                },
                                outcome="succeeded",
                            )
                            if snapshot_event is not None:
                                record_current_event(
                                    "state.delta",
                                    {
                                        "before_hash": before_hash,
                                        "after_hash": after_hash,
                                        "patch": diff_projection(
                                            tick_baseline, tick_after
                                        ),
                                    },
                                    outcome="succeeded",
                                )
                        except Exception:
                            logger.warning(
                                "Unable to record cognitive tick state delta",
                                exc_info=True,
                            )
                    finished_payload: dict[str, Any] = {
                        "elapsed_seconds": elapsed_seconds,
                        "duration_ms": round(
                            max(0.0, time.monotonic() - tick_started_at) * 1000.0,
                            3,
                        ),
                    }
                    if tick_error_type is not None:
                        finished_payload["error_type"] = tick_error_type
                    for status_key in (
                        "biology_status",
                        "maintenance_status",
                        "phase",
                    ):
                        status_value = tick_execution_status.get(status_key)
                        if status_value is not None:
                            finished_payload[status_key] = status_value
                    record_current_event(
                        "cognitive_tick.finished",
                        finished_payload,
                        outcome=tick_outcome,
                    )
                except Exception:
                    logger.warning("Unable to finish cognitive tick journal", exc_info=True)
                finally:
                    try:
                        reset_journal_context(journal_token)
                    except Exception:
                        logger.warning(
                            "Unable to reset cognitive tick journal context",
                            exc_info=True,
                        )
            if gate is not None:
                gate.release()

    def _state_duration_mix(self, dt: float):
        """Partition elapsed tick time using monotonic state residency totals."""
        try:
            normalized_dt = float(dt)
        except (TypeError, ValueError):
            normalized_dt = 0.0
        if not math.isfinite(normalized_dt) or normalized_dt < 0.0:
            normalized_dt = 0.0

        state_machine = self.state_machine
        totals_reader = getattr(state_machine, "duration_totals", None)
        snapshot = totals_reader() if callable(totals_reader) else None
        current_state = getattr(state_machine, "state", AgentState.IDLE)
        if not isinstance(current_state, AgentState):
            current_state = AgentState.IDLE

        if snapshot is None:
            return ({current_state: normalized_dt}, None)

        previous = getattr(self, "_state_duration_checkpoint", {})
        deltas = {
            state: max(
                0.0,
                float(snapshot.get(state, 0.0))
                - float(previous.get(state, 0.0)),
            )
            for state in AgentState
        }
        observed = sum(deltas.values())
        if observed <= 1e-9:
            return ({current_state: normalized_dt}, snapshot)
        scale = normalized_dt / observed
        return ({state: seconds * scale for state, seconds in deltas.items()}, snapshot)

    def _memory_maintenance_due(self) -> bool:
        last = getattr(self, "_last_memory_maintenance_at", None)
        interval = float(getattr(Config, "MEMORY_MAINTENANCE_INTERVAL_SECONDS", 0.0))
        return last is None or time.monotonic() - last >= interval

    @staticmethod
    def _snapshot_tick_biology(ego) -> dict[str, Any]:
        """Capture only RAM fields mutated by the tick's biological phase."""
        with ego.lock:
            fields = {
                name: copy.deepcopy(getattr(ego, name))
                for name in _TICK_BIOLOGY_FIELDS
                if hasattr(ego, name)
            }
            bio_controller = getattr(ego, "bio_controller", None)
            sensitivities_present = hasattr(bio_controller, "sensitivities")
            sensitivities = (
                copy.deepcopy(bio_controller.sensitivities)
                if sensitivities_present
                else None
            )
        return {
            "fields": fields,
            "bio_controller": bio_controller,
            "sensitivities_present": sensitivities_present,
            "sensitivities": sensitivities,
        }

    @staticmethod
    def _restore_tick_biology(ego, snapshot: dict[str, Any]) -> None:
        """Restore a biological snapshot without calling self-locking APIs."""
        with ego.lock:
            for name, value in snapshot["fields"].items():
                setattr(ego, name, copy.deepcopy(value))
            bio_controller = snapshot.get("bio_controller")
            if snapshot.get("sensitivities_present") and bio_controller is not None:
                bio_controller.sensitivities = copy.deepcopy(
                    snapshot.get("sensitivities")
                )

    @staticmethod
    def _snapshot_tick_memory_trace(trace) -> dict[str, Any]:
        """Capture one trace before its in-place decay transition."""
        state = getattr(trace, "__dict__", None)
        if not isinstance(state, dict):
            raise TypeError("cognitive tick memory trace must expose state")
        return copy.deepcopy(state)

    @staticmethod
    def _restore_tick_memory_trace(trace, snapshot: dict[str, Any]) -> None:
        state = getattr(trace, "__dict__", None)
        if not isinstance(state, dict):
            raise TypeError("cognitive tick memory trace must expose state")
        state.clear()
        state.update(copy.deepcopy(snapshot))

    def _decay_tick_memory_trace(
        self,
        trace,
        *,
        stress_level: float,
        decay_time: float,
        is_cancelled,
    ) -> bool:
        """Persist one decay or restore its complete in-memory transition."""
        snapshot = self._snapshot_tick_memory_trace(trace)
        try:
            last_decayed_at = getattr(trace, "last_decayed_at", None)
            if (
                isinstance(last_decayed_at, bool)
                or not isinstance(last_decayed_at, (int, float))
            ):
                last_decayed_at = getattr(trace, "created_at", decay_time)
            elapsed_days = max(
                0.0,
                decay_time - float(last_decayed_at),
            ) / 86400.0
            trace.decay(
                stress_level=stress_level,
                elapsed_days=elapsed_days,
            )
            trace.last_decayed_at = decay_time
            if is_cancelled():
                self._restore_tick_memory_trace(trace, snapshot)
                return False
            self.memory.update_memory(trace)
        except BaseException:
            self._restore_tick_memory_trace(trace, snapshot)
            raise
        return True

    def _cognitive_tick_owned(
        self,
        dt: float = 30.0,
        cancel_event=None,
        *,
        state_durations=None,
        execution_status: dict[str, str] | None = None,
    ):
        """
        Module 1: Vòng tick sinh học trung tâm — chạy mỗi dt giây.
        
        cancel_event is cooperative: it cannot kill a worker thread, but it lets
        the tick stop safely at boundaries after an asyncio timeout.
        """
        def _is_cancelled():
            return cancel_event is not None and cancel_event.is_set()

        def _set_status(**values: str) -> None:
            if execution_status is not None:
                execution_status.update(values)

        biology_snapshot = None
        biology_committed = False
        maintenance_committed = False
        metabolic_gc_requested = False
        _set_status(
            biology_status="not_started",
            maintenance_status="not_started",
            phase="preflight",
        )

        try:
            if _is_cancelled():
                _set_status(outcome="cancelled")
                return False

            try:
                dt = float(dt)
            except (TypeError, ValueError):
                dt = 0.0
            if not math.isfinite(dt) or dt < 0.0:
                dt = 0.0
            if not isinstance(state_durations, dict):
                state_durations = {self.state_machine.state: dt}
            idle_dt = max(0.0, float(state_durations.get(AgentState.IDLE, 0.0)))
            reading_dt = max(
                0.0, float(state_durations.get(AgentState.READING, 0.0))
            )
            thinking_dt = max(
                0.0, float(state_durations.get(AgentState.THINKING, 0.0))
            )
            non_idle_dt = max(0.0, dt - min(dt, idle_dt))

            biology_snapshot = self._snapshot_tick_biology(self.ego)
            _set_status(biology_status="running", phase="biology")

            # 1 & 2. Biological decay + Circadian rhythm
            # SelfModel methods own ego.lock. Keep direct mutations in short,
            # explicit critical sections instead of nesting a non-reentrant
            # lock around self-locking public methods.
            biology_cancelled = False
            with self.ego.lock:
                biology_cancelled = _is_cancelled()
                # Phase 14: Non-linear Metabolism (Exponential Biological Curves)
                # Fatigue tang nhanh hon khi da met (kieu quadratic resistance)
                # f_new = f + rate * dt * (1 + f) — cang met cang mat suc nhanh
                # Chỉ mệt thêm khi đang thức; lúc ngủ SelfModel tự hồi phục.
                from core.engine import sleep_cycle

                if not biology_cancelled and not sleep_cycle.is_asleep(
                    self.ego, time.time()
                ):
                    # Cùng với BioController (~0.01/h) và nhịp ngày đêm, một
                    # ngày thức ~16 giờ đưa fatigue lên ~0.7: buồn ngủ đúng giờ
                    # đi ngủ thay vì gục giữa buổi sáng (trước đây 0.12/h).
                    fatigue_rate = 0.025 / 3600  # baseline per second
                    self.ego.fatigue = min(
                        1.0,
                        self.ego.fatigue
                        + fatigue_rate * dt * (1 + self.ego.fatigue * 0.5),
                    )

            if biology_cancelled:
                self._restore_tick_biology(self.ego, biology_snapshot)
                _set_status(
                    biology_status="rolled_back",
                    outcome="cancelled",
                )
                return False

            idle_seconds = max(0.0, time.time() - self.last_interaction_time)
            self.ego.apply_biological_decay(dt, idle_seconds)

            if _is_cancelled():
                self._restore_tick_biology(self.ego, biology_snapshot)
                _set_status(
                    biology_status="rolled_back",
                    outcome="cancelled",
                )
                return False

            with self.ego.lock:
                # Stress giam theo exponential decay (half-life model, khong tuyen tinh)
                # s_new = s * exp(-decay_rate * dt)
                stress_decay = math.exp(-0.002 * dt / 60)
                self.ego.stress = max(0.0, self.ego.stress * stress_decay)

                # Phase 8: Metabolism (Energy & ATP)
                # Energy hồi phục tự nhiên (0.01 mỗi phút)
                self.ego.energy = min(1.0, self.ego.energy + 0.01 * dt / 60)
                # Integrate state-specific metabolism from the residency
                # ledger. Catch-up after a busy actor must not look like IDLE.
                # Tốc độ tính theo giờ (IDLE 0.2/h, bận 0.04/h) để ATP thực sự
                # cạn dần khi thức; hồi phục hoàn toàn diễn ra trong lúc ngủ.
                atp_recovery = (
                    (0.2 * idle_dt) + (0.04 * non_idle_dt)
                ) / 3600
                self.ego.atp_level = min(1.0, self.ego.atp_level + atp_recovery)

                if reading_dt > 0.0:
                    self.ego.curiosity = max(0.0, self.ego.curiosity - 0.002 * reading_dt / 60)
                    # Đọc sách tiêu tốn Energy
                    self.ego.energy = max(0.0, self.ego.energy - 0.005 * reading_dt / 60)

                # Giảm nhẹ trừ gốc (0.005 -> 0.001) chờ tích hợp Token-based cost bên trong `llm.py`
                if thinking_dt > 0.0:
                    self.ego.fatigue = min(1.0, self.ego.fatigue + 0.001 * thinking_dt / 60)
                    # Suy nghĩ sâu (LLM) tiêu tốn ATP mạnh
                    self.ego.atp_level = max(0.0, self.ego.atp_level - 0.05 * thinking_dt / 60)

            if _is_cancelled():
                self._restore_tick_biology(self.ego, biology_snapshot)
                _set_status(
                    biology_status="rolled_back",
                    outcome="cancelled",
                )
                return False

            # Phân hệ 9 (Sprint D): filesystem traversal must not hold ego.lock.
            try:
                def get_dir_size(path):
                    total = 0
                    with os.scandir(path) as it:
                        for entry in it:
                            if entry.is_file():
                                total += entry.stat().st_size
                            elif entry.is_dir():
                                total += get_dir_size(entry.path)
                    return total

                if os.path.exists(Config.CHROMA_DB_PATH):
                    db_size = get_dir_size(Config.CHROMA_DB_PATH)
                    if db_size > Config.MAX_STORAGE_SIZE:
                        pressure = (db_size - Config.MAX_STORAGE_SIZE) / (100 * 1024 * 1024)
                        storage_stress = min(0.3, pressure * 0.1)
                        self.ego.adjust_attribute('stress', storage_stress)
                        if storage_stress > 0.05:
                            print(f"{Fore.LIGHTRED_EX}🧠 [STORAGE PRESSURE]: Bộ nhớ quá tải ({db_size/1024/1024:.1f}MB). Aura cảm thấy nặng đầu...{Style.RESET_ALL}")
            except Exception as e:
                logger.debug(f"Failed to calculate storage pressure: {e}")

            if _is_cancelled():
                self._restore_tick_biology(self.ego, biology_snapshot)
                _set_status(
                    biology_status="rolled_back",
                    outcome="cancelled",
                )
                return False

            deferred_circadian = getattr(
                self.ego,
                "apply_circadian_rhythm_deferred",
                None,
            )
            if callable(deferred_circadian):
                metabolic_gc_requested = bool(deferred_circadian())
            else:
                # Compatibility for injected SelfModel-shaped test doubles.
                # A model with storage attached must expose the deferred API;
                # otherwise calling its legacy method could delete memory
                # before the biological transaction commits.
                if getattr(self.ego, "memory_manager", None) is not None:
                    raise RuntimeError(
                        "storage-backed ego requires deferred circadian GC"
                    )
                self.ego.apply_circadian_rhythm()

            if _is_cancelled():
                self._restore_tick_biology(self.ego, biology_snapshot)
                _set_status(
                    biology_status="rolled_back",
                    outcome="cancelled",
                )
                return False

            biology_committed = True
            _set_status(
                biology_status="committed",
                maintenance_status="running",
                phase="memory",
            )

            # 3 & 4. Memory decay + Garbage collection
            # Both read the whole store. Decay is checkpointed per memory by
            # wall clock, so a slower cadence loses nothing; a metabolic GC
            # request from the circadian phase still runs immediately.
            if not (metabolic_gc_requested or self._memory_maintenance_due()):
                _set_status(maintenance_status="skipped", phase="dashboard")
                if _is_cancelled():
                    _set_status(outcome="cancelled")
                    return True
                self._dump_mind_state()
                _set_status(phase="committed", outcome="succeeded")
                return True

            # MemoryManager methods own memory.lock. Snapshot ego state first so
            # the two subsystem locks are never held at the same time.
            with self.ego.lock:
                stress_level = self.ego.stress

            if _is_cancelled():
                _set_status(
                    maintenance_status="cancelled",
                    outcome="cancelled",
                )
                return True
            import random
            with memory_context_scope(
                maintenance_memory_context(
                    origin_kind="memory_decay",
                    origin_source="cognitive_tick",
                )
            ):
                mems = self.memory.get_all()
                if _is_cancelled():
                    _set_status(
                        maintenance_status="cancelled",
                        outcome="cancelled",
                    )
                    return True
                if mems:
                    sample_size = max(1, len(mems) // 10)
                    sample = random.sample(list(mems), k=sample_size)
                    decay_time = time.time()
                    for m in sample:
                        if _is_cancelled():
                            _set_status(
                                maintenance_status="cancelled",
                                outcome="cancelled",
                            )
                            return True
                        if not self._decay_tick_memory_trace(
                            m,
                            stress_level=stress_level,
                            decay_time=decay_time,
                            is_cancelled=_is_cancelled,
                        ):
                            _set_status(
                                maintenance_status="cancelled",
                                outcome="cancelled",
                            )
                            return True

                if _is_cancelled():
                    _set_status(
                        maintenance_status="cancelled",
                        outcome="cancelled",
                    )
                    return True
                _set_status(phase="memory_gc")
                if metabolic_gc_requested:
                    logger.debug(
                        "Fulfilling deferred circadian metabolic GC request"
                    )
                self.memory.enforce_garbage_collection()

            maintenance_committed = True
            self._last_memory_maintenance_at = time.monotonic()
            _set_status(maintenance_status="committed", phase="dashboard")
            if _is_cancelled():
                _set_status(outcome="cancelled")
                return True

            # 5. Dump mind state cho Dashboard
            self._dump_mind_state()
            _set_status(phase="committed", outcome="succeeded")
            return True

        except BaseException as exc:
            if not biology_committed:
                if biology_snapshot is not None:
                    self._restore_tick_biology(self.ego, biology_snapshot)
                _set_status(
                    biology_status="rolled_back",
                    phase="biology",
                    error_type=type(exc).__name__,
                    outcome="failed",
                )
                consumed = False
            else:
                failed_phase = "dashboard" if maintenance_committed else "memory"
                if (
                    execution_status is not None
                    and execution_status.get("phase") == "memory_gc"
                ):
                    failed_phase = "memory_gc"
                _set_status(
                    maintenance_status=(
                        "committed" if maintenance_committed else "failed"
                    ),
                    phase=failed_phase,
                    error_type=type(exc).__name__,
                    outcome="failed",
                )
                consumed = True
            if not isinstance(exc, Exception):
                raise
            logger.error("cognitive_tick failed", exc_info=True)
            return consumed


    def shutdown(self, *, consolidate: bool = False) -> bool:
        """Close producers, wait for mutation owners, then persist state.

        Persistence is deliberately skipped when a worker misses its shutdown
        deadline: saving while a cognitive mutation is still running would
        create a torn snapshot. The method is idempotent after a successful
        shutdown and reports whether a fully quiescent save completed.
        """
        shutdown_lock = getattr(self, "_shutdown_lock", None)
        if shutdown_lock is None:
            # Compatibility for small __new__-based test doubles.
            shutdown_lock = threading.Lock()
            self._shutdown_lock = shutdown_lock

        with shutdown_lock:
            if getattr(self, "_shutdown_complete", False):
                return getattr(self, "_shutdown_result", True) is not False

            if consolidate:
                logger.warning(
                    "Shutdown no longer simulates a sleep day; submit_sleep() "
                    "is the explicit consolidation/day-advance operation"
                )

            state_machine = getattr(self, "state_machine", None)
            if (
                state_machine is not None
                and state_machine.state != AgentState.SHUTDOWN
                and not state_machine.transition(AgentState.SHUTDOWN)
            ):
                logger.error("Unable to transition cognitive engine to SHUTDOWN")
                return False

            # Close the actor first. This cancels any ticket awaited by the
            # autonomous web/Discord producer and lets that loop exit promptly.
            interaction_actor = getattr(self, "interaction_actor", None)
            actor_stopped = True
            if interaction_actor is not None:
                actor_stopped = interaction_actor.shutdown(
                    drain=False,
                    timeout=Config.INTERACTION_SHUTDOWN_TIMEOUT_SECONDS,
                )

            autonomous = getattr(self, "autonomous", None)
            autonomous_stopped = True
            if autonomous is not None:
                autonomous_result = autonomous.stop(
                    timeout=Config.AUTONOMOUS_SHUTDOWN_TIMEOUT_SECONDS
                )
                # Older test doubles returned None after a successful stop.
                autonomous_stopped = autonomous_result is not False

            discord_stopped = True
            discord_bridge = getattr(self, "discord_bridge", None)
            bridge_stop = getattr(discord_bridge, "stop", None)
            if callable(bridge_stop):
                try:
                    bridge_result = bridge_stop(
                        timeout=Config.AUTONOMOUS_SHUTDOWN_TIMEOUT_SECONDS
                    )
                    discord_stopped = bridge_result is not False
                except Exception:
                    logger.error("Discord cleanup during shutdown failed", exc_info=True)
                    discord_stopped = False

            if not actor_stopped or not autonomous_stopped:
                logger.warning(
                    "CognitiveEngine shutdown degraded: actor_stopped=%s, "
                    "autonomous_stopped=%s; skipping state save to avoid a torn snapshot",
                    actor_stopped,
                    autonomous_stopped,
                )
                return False

            gate = getattr(self, "_runtime_mutation_gate", None)
            gate_acquired = gate is None or gate.acquire(
                timeout=Config.INTERACTION_SHUTDOWN_TIMEOUT_SECONDS
            )
            if not gate_acquired:
                logger.warning(
                    "Runtime mutation gate remained owned after workers stopped; "
                    "skipping state save to avoid a torn snapshot"
                )
                return False

            persistence_ok = True
            ledger_stopped = True
            try:
                reader = getattr(self, "reader", None)
                if reader is not None and callable(getattr(reader, "stop", None)):
                    try:
                        reader.stop()
                    except Exception:
                        logger.error("Reader cleanup during shutdown failed", exc_info=True)
                        discord_stopped = False
                self.ego.save_state()
                if discord_stopped and getattr(self, "_owns_memory", True):
                    memory = getattr(self, "memory", None)
                    close_memory = getattr(memory, "close", None)
                    if callable(close_memory):
                        close_memory()
            except Exception:
                logger.error("CognitiveEngine persistence during shutdown failed", exc_info=True)
                persistence_ok = False
            finally:
                # Actor/autonomous producers are stopped and this thread owns
                # the mutation gate, so no interaction or cognitive tick can
                # still append to the durable operation ledger.
                ledger_stopped = self._close_owned_operation_ledger_once()
                if gate is not None:
                    gate.release()

            if not persistence_ok:
                return False

            self._shutdown_complete = True
            self._shutdown_result = discord_stopped and ledger_stopped
            if not discord_stopped:
                logger.warning(
                    "CognitiveEngine state was saved, but an optional transport "
                    "or reader cleanup did not finish cleanly; retaining the "
                    "writer lease for process safety"
                )
            if not ledger_stopped:
                logger.warning(
                    "CognitiveEngine state was saved, but the operation ledger "
                    "did not close cleanly"
                )
            logger.info("CognitiveEngine shutdown complete. Ego state saved.")
            return self._shutdown_result

    def _dump_mind_state(self):
        """Xuất trạng thái sinh lý và tâm lý ra JSON để Dashboard đọc (Idea 5)"""
        from core.utils import atomic_write_json
        from config import Config
        try:
            state = {
                "name": self.ego.name,
                "mood": self.ego.mood,
                "stress": self.ego.stress,
                "fatigue": self.ego.fatigue,
                "integrity": self.ego.integrity,
                "curiosity": self.ego.curiosity,
                "social_need": self.ego.social_need,
                "is_stranger": self.ego.is_stranger,
                "current_intimacy": self.ego.current_intimacy,
                "is_identity_crisis": self.ego.is_identity_crisis,
                "active_goals": self.ego.get_active_goals(),
                "timestamp": time.time()
            }
            actor = getattr(self, "interaction_actor", None)
            if actor is not None:
                actor_state = actor.snapshot()
                state["interaction_runtime"] = {
                    "queued": actor_state.queued,
                    "capacity": actor_state.capacity,
                    "active_request_id": actor_state.active_request_id,
                    "submitted": actor_state.submitted,
                    "succeeded": actor_state.succeeded,
                    "failed": actor_state.failed,
                    "cancelled": actor_state.cancelled,
                    "rejected_full": actor_state.rejected_full,
                }
            atomic_write_json(Config.MIND_STATE_FILE, state)
        except Exception:
            logger.warning("Failed to dump mind state", exc_info=True)

