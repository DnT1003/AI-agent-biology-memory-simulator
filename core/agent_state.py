"""
core/agent_state.py — State Machine tường minh (Phase 10, Module 6)

Thay thế các biến boolean rải rác (is_thinking, is_reading, ...) bằng
một trạng thái duy nhất, rõ ràng và kiểm tra được.

Dùng:
    from core.agent_state import AgentState, StateMachine

    sm = StateMachine()
    sm.transition(AgentState.THINKING)
    print(sm.state)           # AgentState.THINKING
    sm.transition(AgentState.IDLE)

    # Kiểm tra nhanh
    if sm.is_idle(): ...
    if sm.is_in(AgentState.READING, AgentState.THINKING): ...
"""

import time
from enum import Enum, auto
from core.event_journal import record_current_event
from core.logger import get_logger

logger = get_logger("agent_state")


def _record_state_change(
    previous: "AgentState", current: "AgentState", *, forced: bool
) -> None:
    """Record after the state lock is released and never affect transitions."""

    try:
        record_current_event(
            "runtime.state_changed",
            {
                "from_state": previous.name,
                "to_state": current.name,
                "forced": forced,
            },
            outcome="succeeded",
        )
    except Exception:
        logger.warning("Unable to record state transition", exc_info=True)


class AgentState(Enum):
    """Các trạng thái chính của CognitiveEngine."""
    IDLE      = auto()   # Không làm gì, chờ input
    THINKING  = auto()   # Đang xử lý LLM call
    READING   = auto()   # Đang đọc sách trong background
    SLEEPING  = auto()   # Đang consolidate memory (sleep phase)
    SHUTDOWN  = auto()   # Đã shutdown, không nhận lệnh mới


# Transition table: từ state X có thể đến những state nào
_ALLOWED_TRANSITIONS: dict[AgentState, set] = {
    AgentState.IDLE:     {AgentState.THINKING, AgentState.READING, AgentState.SLEEPING, AgentState.SHUTDOWN},
    AgentState.THINKING: {AgentState.IDLE, AgentState.SHUTDOWN},
    AgentState.READING:  {AgentState.IDLE, AgentState.SHUTDOWN},
    AgentState.SLEEPING: {AgentState.IDLE, AgentState.SHUTDOWN},
    AgentState.SHUTDOWN: set(),  # Không đi đâu được sau khi shutdown
}


class StateMachine:
    """
    State machine nhỏ, thread-safe wrapper xung quanh AgentState.

    Ghi chú: StateMachine không dùng lock nội bộ — nếu dùng trong
    môi trường đa luồng, hãy bảo vệ bằng _ego_lock hoặc _memory_lock
    của CognitiveEngine.
    """

    def __init__(self, initial: AgentState = AgentState.IDLE):
        import threading
        self._lock = threading.Lock()
        self._state = initial
        self._state_entered_at = time.monotonic()
        self._duration_totals = {state: 0.0 for state in AgentState}
        logger.info(f"StateMachine khởi tạo: {self._state.name}")

    @property
    def state(self) -> AgentState:
        with self._lock:
            return self._state

    def transition(self, new_state: AgentState) -> bool:
        """
        Chuyển state. Trả về True nếu thành công, False nếu transition không hợp lệ.
        Không raise exception — hệ thống tiếp tục hoạt động dù transition bị chặn.
        """
        with self._lock:
            previous_state = self._state
            allowed = _ALLOWED_TRANSITIONS.get(self._state, set())
            if new_state not in allowed:
                logger.warning(
                    f"[STATE MACHINE] Transition bị chặn: {self._state.name} → {new_state.name} "
                    f"(allowed: {[s.name for s in allowed]})"
                )
                return False
            transition_time = time.monotonic()
            self._duration_totals[self._state] += max(
                0.0, transition_time - self._state_entered_at
            )
            logger.debug(f"[STATE MACHINE] {self._state.name} → {new_state.name}")
            self._state = new_state
            self._state_entered_at = transition_time
        _record_state_change(previous_state, new_state, forced=False)
        return True

    def force(self, new_state: AgentState):
        """Override trực tiếp, dùng khi cần recover từ lỗi."""
        with self._lock:
            previous_state = self._state
            transition_time = time.monotonic()
            self._duration_totals[self._state] += max(
                0.0, transition_time - self._state_entered_at
            )
            logger.warning(f"[STATE MACHINE] FORCE override: {self._state.name} → {new_state.name}")
            self._state = new_state
            self._state_entered_at = transition_time
        _record_state_change(previous_state, new_state, forced=True)

    def duration_totals(self) -> dict[AgentState, float]:
        """Return monotonic cumulative seconds spent in every state."""
        with self._lock:
            totals = dict(self._duration_totals)
            totals[self._state] += max(
                0.0, time.monotonic() - self._state_entered_at
            )
            return totals

    # ------- Helper predicates ------- #

    def is_idle(self) -> bool:
        return self.state == AgentState.IDLE

    def is_busy(self) -> bool:
        return self.state in (AgentState.THINKING, AgentState.READING, AgentState.SLEEPING)

    def is_in(self, *states: AgentState) -> bool:
        return self.state in states

    def is_shutdown(self) -> bool:
        return self.state == AgentState.SHUTDOWN

    def __repr__(self) -> str:
        return f"StateMachine({self.state.name})"
