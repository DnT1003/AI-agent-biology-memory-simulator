"""Deterministic multi-day simulation of Aura's life.

Drives the real behaviour code over simulated days, without waiting: the
cognitive tick, SelfModel biology, the autonomous decision loop and its pacer,
the interaction pipeline and nightly identity reflection. Only the outside
world is fake: a simulated clock, a scripted user, a scripted LLM and an
in-memory memory store.

    report = run_week(seed=7)
    print(format_report(report))

Content metrics (repetition, assistant-speak, follow-ups) are computed from
what Aura said. With the scripted LLM they only check the plumbing; pass a
real ``llm`` to measure the model itself.

Known gaps versus production: no vector search (keyword recall), sleep runs
only its homeostasis commit, identity reflection and threshold reroll (no dream
consolidation), and transports are recorded instead of delivered.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import math
import os
import random
import re
import tempfile
import threading
import time as _real_time
from dataclasses import dataclass, field
from datetime import datetime as _real_datetime
from datetime import timedelta as _real_timedelta
from types import SimpleNamespace
from typing import Callable, Optional
from unittest.mock import patch

STEP_SECONDS = 60.0
QUIET_START, QUIET_END = 23, 7
# Monday 2026-10-19 08:00 local time.
DEFAULT_START = _real_datetime(2026, 10, 19, 8, 0).timestamp()


# --------------------------------------------------------------------- clock
class SimClock:
    def __init__(self, start: float):
        self.now = float(start)
        self.start = float(start)

    def time(self) -> float:
        return self.now

    def monotonic(self) -> float:
        return 10_000.0 + self.now - self.start

    def time_ns(self) -> int:
        return int(self.now * 1_000_000_000)

    def advance(self, seconds: float) -> None:
        self.now += float(seconds)


class _TimeProxy:
    """Stand-in for the ``time`` module inside simulated modules."""

    def __init__(self, clock: SimClock):
        self._clock = clock

    def time(self):
        return self._clock.time()

    def monotonic(self):
        return self._clock.monotonic()

    def time_ns(self):
        return self._clock.time_ns()

    def __getattr__(self, name):
        return getattr(_real_time, name)


def _datetime_for(clock: SimClock):
    class SimDatetime(_real_datetime):
        @classmethod
        def now(cls, tz=None):
            return _real_datetime.fromtimestamp(clock.time(), tz)

    return SimDatetime


_TIME_MODULES = (
    "core.agent_state",
    "core.memory",
    "core.self_model",
    "core.engine.autonomous",
    "core.engine.bio_controller",
    "core.engine.cognitive_engine",
    "core.engine.interaction",
    "core.engine.memory_ops",
    "core.engine.perception",
)
_DATETIME_MODULES = (
    "core.self_model",
    "core.engine.autonomous",
    "core.engine.interaction",
    "core.engine.perception",
)


# ------------------------------------------------------------- user script
@dataclass(frozen=True)
class UserMessage:
    day: int  # 0 = first simulated day
    hour: int
    minute: int
    text: str


# Monday..Sunday. Day 2-3: the owner disappears. Day 4: a quarrel and repair.
DEFAULT_SCRIPT: tuple[UserMessage, ...] = (
    UserMessage(0, 8, 30, "Chào buổi sáng Aura, hôm nay anh đi làm sớm"),
    UserMessage(0, 12, 15, "Trưa nay anh ăn bún chả, buồn cười lắm vì quán đông kinh khủng"),
    UserMessage(0, 20, 0, "Tối rồi, em đang đọc gì thế?"),
    UserMessage(0, 20, 5, "Nghe hay đấy, kể anh nghe đi"),
    UserMessage(0, 22, 45, "Thôi anh đi ngủ đây, ngủ ngon nhé"),
    UserMessage(1, 9, 0, "Sáng nay anh mệt quá, tối qua ngủ ít"),
    UserMessage(1, 9, 5, "Anh vào họp đến 11h nhé, lát nói chuyện"),
    UserMessage(1, 19, 30, "Thứ 4 này anh có buổi phỏng vấn quan trọng, hơi lo"),
    UserMessage(1, 21, 0, "Cảm ơn em đã động viên, buồn cười thật"),
    # Day 2 and day 3: silence.
    UserMessage(4, 18, 0, "Anh xin lỗi vì mất tích hai ngày"),
    UserMessage(4, 18, 10, "Em phiền quá đấy! Đừng nhắn anh nhiều thế!!"),
    UserMessage(4, 18, 40, "Anh xin lỗi, anh nói nặng lời quá. Anh đang stress vụ phỏng vấn"),
    UserMessage(5, 0, 30, "Em ngủ chưa? Anh không ngủ được"),
    UserMessage(5, 10, 0, "Hôm nay cuối tuần, anh rảnh rỗi cả ngày"),
    UserMessage(5, 15, 0, "Em có muốn nghe anh kể chuyện buổi phỏng vấn không?"),
    UserMessage(6, 9, 30, "Chủ nhật vui vẻ nhé Aura"),
    UserMessage(6, 9, 40, "Không phải thế, buổi phỏng vấn là thứ 4 chứ không phải thứ 5"),
    UserMessage(6, 21, 0, "Tuần này nhiều chuyện thật, cảm ơn em"),
)
OPEN_LOOPS = (("phỏng vấn", 1),)  # (keyword the owner raised, day raised)


# ------------------------------------------------------------- scripted LLM
_REFUSAL_PATTERNS = (r"\bkhông muốn\b", r"\bthôi\b.*\blười\b", r"\bem không làm\b")


class ScriptedLLM:
    """Deterministic stand-in: recognises each prompt kind by its marker."""

    def __init__(self, identity_script: Optional[Callable[[int], str]] = None):
        self.calls: list[tuple[str, str]] = []
        self.night = 0
        self._identity_script = identity_script or _default_identity_script
        self._turn = 0
        self.assistant_injected = 0

    def _kind(self, prompt: str) -> str:
        if "open_loops" in prompt:
            return "enrichment"
        if "Aura vừa đọc xong" in prompt:
            return "reading"
        if "CHỦ ĐỘNG nhắn tin" in prompt:
            return "rumination" if "Rumination" in prompt else "ping"
        if "BẢN SẮC HIỆN TẠI CỦA BẠN" in prompt:
            return "identity"
        if "MỐI QUAN HỆ" in prompt:
            return "graph"
        if "THÁI ĐỘ RÕ RÀNG" in prompt:
            return "values"
        if '"response"' in prompt or "response" in prompt and "JSON" in prompt:
            return "reply"
        return "text"

    @staticmethod
    def _now_from(prompt: str):
        match = re.search(r"(\d{2})/(\d{2})/(\d{4}) (\d{2}):(\d{2})", prompt)
        if not match:
            return None
        day, month, year, hour, minute = map(int, match.groups())
        return _real_datetime(year, month, day, hour, minute)

    def _enrichment(self, prompt: str) -> dict:
        """What a good extractor would return for the scripted owner lines."""
        user_line = prompt.split("User nói:", 1)[-1].split("Aura (AI)", 1)[0].lower()
        now = self._now_from(prompt)
        payload = {"relations": [], "values": [], "open_loops": [], "user_busy": None}
        if now is None:
            return payload
        if "phỏng vấn" in user_line and "thứ 4" in user_line:
            days_ahead = (2 - now.weekday()) % 7  # Wednesday
            due = (now + _real_timedelta(days=days_ahead)).strftime("%Y-%m-%d")
            payload["open_loops"].append(
                {"owner": "user", "about": "buổi phỏng vấn quan trọng", "keyword": "phỏng vấn", "due": due}
            )
        if "họp đến 11h" in user_line:
            payload["user_busy"] = {"until": now.strftime("%Y-%m-%d") + " 11:00", "reason": "đi họp"}
        return payload

    @staticmethod
    def _mention(prompt: str) -> str:
        # A model that uses its context brings the open loop up.
        if "phỏng vấn" not in prompt:
            return ""
        if "LÝ DO NHẮN" in prompt or "User đã có việc" in prompt:
            return " [SEND] mà buổi phỏng vấn của anh thế nào rồi?"
        if "User sắp có việc" in prompt:
            return " [SEND] chúc anh phỏng vấn may mắn nha"
        return ""

    def generate_json(self, prompt, *args, **kwargs):
        prompt = str(prompt)
        kind = self._kind(prompt)
        self.calls.append(("json", kind))
        if kind == "enrichment":
            return self._enrichment(prompt), 0.0
        if kind == "reading":
            return {
                "reflection": "Xuân Tóc Đỏ lém lỉnh quá, mình vừa buồn cười vừa hơi ghét.",
                "feeling": 0.4,
                "share": "Anh ơi, Xuân Tóc Đỏ trong Số đỏ lém lỉnh ghê",
            }, 0.0
        if kind == "graph":
            return {"relations": []}, 0.0
        if kind in ("ping", "rumination"):
            self._turn += 1
            return {
                "thought": "nhớ anh",
                "response": f"Anh ơi [SEND] em đang nghĩ về anh (lần {self._turn}){self._mention(prompt)}",
            }, 0.0
        self._turn += 1
        return {
            "valence": 0.2,
            "arousal": 0.3,
            "importance": 0.5,
            "type": "episodic",
            "internal_monologue": "ổn",
            "thought": "trả lời tự nhiên",
            "action": None,
            "response": self._reply_text(prompt),
        }, 0.0

    # Every 4th reply drifts into assistant register, as real LLMs do; the
    # style filter must remove it before anything is said.
    ASSISTANT_DRIFT = (
        "Chắc chắn rồi!" + chr(10) + "## Gợi ý" + chr(10) + "- **Nghỉ ngơi** nhé" + chr(10)
        + "- Uống nước" + chr(10) + "Mình có thể giúp gì thêm cho anh không?"
    )

    def _reply_text(self, prompt: str) -> str:
        base = f"Dạ em nghe nè [SEND] kể tiếp đi anh ({self._turn}){self._mention(prompt)}"
        if self._turn % 4 == 0:
            self.assistant_injected += 1
            return self.ASSISTANT_DRIFT + " [SEND] " + base
        return base

    def generate_text(self, prompt, *args, **kwargs):
        kind = self._kind(str(prompt))
        self.calls.append(("text", kind))
        if kind == "identity":
            self.night += 1
            return json.dumps({
                "insight": self._identity_script(self.night),
                "actionable_lessons": ["Lắng nghe anh nhiều hơn"],
                "value_updates": [],
            }, ensure_ascii=False), 0.0
        if kind == "values":
            return "[]", 0.0
        return "Em thấy chương này buồn nhưng đẹp.", 0.0


def _default_identity_script(night: int) -> str:
    base = "Tôi là người bạn tò mò, thích đọc sách và quan tâm anh"
    if night == 5:
        # The night after the quarrel: a one-off drastic self-image.
        return "Mình chỉ là cỗ máy phiền phức không ai cần."
    return f"{base}, và hôm nay tôi học được thêm một điều nhỏ (đêm {night})."


# ------------------------------------------------------- any-LLM wrappers
PROMPT_MARKERS = (
    "[BẠN ĐANG]", "[HƠI CHÁN]", "[TRẢ LỜI MUỘN]", "VỪA BỊ ĐÁNH THỨC",
    "[KHÚC MẮC]", "[QUYỀN TỪ CHỐI]", "[NGƯỢNG]", "[KỶ NIỆM VUI CHUNG]",
    "[CẢM XÚC LẪN LỘN]", "[VIỆC GẤP]",
)


class PromptRecorder:
    """Counts what our code put into prompts, whatever LLM answers them."""

    def __init__(self, inner):
        self.inner = inner
        self.markers = {marker: 0 for marker in PROMPT_MARKERS}
        self.recap_turns = 0
        self.calls = 0
        self.failures = 0
        self.seconds = 0.0

    def _record(self, prompt):
        prompt = str(prompt)
        if "TỪ LẦN CUỐI NÓI CHUYỆN" in prompt:
            self.recap_turns += 1
        for marker in PROMPT_MARKERS:
            if marker in prompt:
                self.markers[marker] += 1

    def _call(self, method, prompt, args, kwargs):
        self.calls += 1
        started = _real_time.monotonic()
        try:
            return getattr(self.inner, method)(prompt, *args, **kwargs)
        except Exception:
            self.failures += 1
            raise
        finally:
            self.seconds += _real_time.monotonic() - started

    def generate_json(self, prompt, *args, **kwargs):
        self._record(prompt)
        return self._call("generate_json", prompt, args, kwargs)

    def generate_text(self, prompt, *args, **kwargs):
        self._record(prompt)
        return self._call("generate_text", prompt, args, kwargs)

    def __getattr__(self, name):
        return getattr(self.inner, name)


class RateLimitedLLM:
    """Real-time pacing for free/local endpoints: the simulated week runs in
    seconds, a real model must not be called faster than ``rpm`` per minute.
    Rate-limit (429) and transport failures back off and retry."""

    def __init__(self, inner, rpm: float = 0.0, retries: int = 4, backoff_seconds: float = 15.0,
                 sleep=_real_time.sleep, clock=_real_time.monotonic):
        self.inner = inner
        self.interval = 60.0 / rpm if rpm and rpm > 0 else 0.0
        self.retries = retries
        self.backoff_seconds = backoff_seconds
        self._sleep, self._clock = sleep, clock
        self._next_at = 0.0
        self.retried = 0

    def _pace(self):
        wait = self._next_at - self._clock()
        if wait > 0:
            self._sleep(wait)
        self._next_at = self._clock() + self.interval

    @staticmethod
    def _retryable(error) -> bool:
        text = f"{type(error).__name__} {error} {getattr(error, '__cause__', '')}"
        return "429" in text or "Transport" in text or "Timeout" in text

    def _call(self, method, prompt, args, kwargs):
        for attempt in range(self.retries + 1):
            self._pace()
            try:
                return getattr(self.inner, method)(prompt, *args, **kwargs)
            except Exception as error:
                if attempt == self.retries or not self._retryable(error):
                    raise
                self.retried += 1
                self._sleep(self.backoff_seconds * (attempt + 1))

    def generate_json(self, prompt, *args, **kwargs):
        return self._call("generate_json", prompt, args, kwargs)

    def generate_text(self, prompt, *args, **kwargs):
        return self._call("generate_text", prompt, args, kwargs)

    def __getattr__(self, name):
        return getattr(self.inner, name)


# ------------------------------------------------------------ fake world
class SimMemory:
    """Keyword-recall memory store with the MemoryManager methods in use."""

    def __init__(self, clock: SimClock):
        self.clock = clock
        self.traces = []
        self.store = SimpleNamespace(update_meta=lambda *a, **k: None, update_vector=lambda *a, **k: None)

    def _stamp(self, trace):
        # MemoryTrace defaults captured the real time.time at import.
        if abs(getattr(trace, "created_at", 0.0) - self.clock.time()) > 3600 * 24 * 30:
            trace.created_at = self.clock.time()
            trace.last_recalled = self.clock.time()
        return trace

    def add_memory(self, trace):
        self.traces.append(self._stamp(trace))

    def add_memories(self, traces):
        for trace in traces:
            self.add_memory(trace)

    def update_memory(self, trace):
        if trace not in self.traces:
            self.traces.append(self._stamp(trace))

    def upsert_memory(self, trace):
        self.update_memory(trace)

    def get_all(self):
        return list(self.traces)

    def search_memories(self, query, top_k=3, **_kwargs):
        words = set(re.findall(r"\w+", str(query).lower()))
        scored = []
        for trace in self.traces:
            overlap = len(words & set(re.findall(r"\w+", trace.content.lower())))
            if overlap:
                scored.append((overlap, trace))
        scored.sort(key=lambda item: -item[0])
        # MemoryManager returns (similarity score, trace) pairs.
        return [(min(1.0, 0.5 + 0.1 * overlap), trace) for overlap, trace in scored[:top_k]]

    def chronological_recall(self, *args, **kwargs):
        return []

    def remove(self, memory_id):
        self.traces = [t for t in self.traces if t.id != memory_id]

    def remove_many(self, memory_ids):
        ids = set(memory_ids)
        self.traces = [t for t in self.traces if t.id not in ids]

    def enforce_garbage_collection(self):
        return None


class SimPerception:
    mode = "native"
    _NEG = ("phiền", "mệt", "lo", "stress", "xin lỗi", "nặng lời")
    _POS = ("cảm ơn", "vui", "hay", "buồn cười", "rảnh")

    def analyze(self, text):
        lowered = text.lower()
        if any(word in lowered for word in self._NEG):
            return {"valence": -0.6, "arousal": 0.8, "importance": 0.6}
        if any(word in lowered for word in self._POS):
            return {"valence": 0.6, "arousal": 0.5, "importance": 0.5}
        return {"valence": 0.0, "arousal": 0.3, "importance": 0.4}


class SimReader:
    def __init__(self):
        self.chapter = 0
        self.last_material_new_book = False

    def get_next_reading_material(self):
        self.chapter += 1
        self.last_material_new_book = self.chapter == 1
        return f"[Sách đã đọc - Số đỏ] Chương {self.chapter}", "Xuân Tóc Đỏ bước vào phố..."

    def get_status(self):
        return "Đang đọc Số đỏ"

    def set_novel_by_url(self, url):
        return "ok"

    def stop(self):
        return None


# ------------------------------------------------------------------ report
@dataclass
class DayStats:
    day: int
    user_messages: int = 0
    replies: int = 0
    pings: int = 0
    quiet_hour_pings: int = 0
    sleeps: int = 0  # sleep periods that started this day (night + naps)
    naps: int = 0
    readings: int = 0
    anxiety_stages: int = 0
    collapses: int = 0  # replies refused because fatigue hit today's limit
    mood_mean: float = 0.0
    fatigue_max: float = 0.0
    _mood_samples: list = field(default_factory=list, repr=False)


@dataclass
class SimReport:
    seed: int
    days: list[DayStats]
    bio_ranges: dict[str, tuple[float, float]]
    non_finite_fields: list[str]
    ping_gaps_in_silence_hours: list[float]
    identity_by_night: list[str]
    pending_by_night: list[str]
    identity_drift: list[float]
    repetition_rate: float
    phrase_repetition_rate: float
    assistant_phrase_rate: float
    refusal_rate: float
    open_loop_follow_ups: dict[str, bool]
    send_tag_leaks: int
    pings_while_owner_busy: int = 0
    prompt_markers: dict = field(default_factory=dict)
    friction_after_message: list = field(default_factory=list)  # (stamp, friction)
    inside_jokes: int = 0
    assistant_injected: int = 0
    llm_calls: int = 0
    llm_failures: int = 0
    llm_seconds: float = 0.0
    failed_turns: list = field(default_factory=list)
    boredom_max: float = 0.0
    reading_feelings: list = field(default_factory=list)
    recap_turns: int = 0
    open_loops_remembered: int = 0
    sleep_times: list[str] = field(default_factory=list)  # "onset -> wake (kind)"
    aura_messages: list[tuple[float, str, str, str]] = field(default_factory=list)

    def to_dict(self):
        data = self.__dict__.copy()
        data["days"] = [
            {k: v for k, v in d.__dict__.items() if not k.startswith("_")} for d in self.days
        ]
        return data


def _hour(ts: float) -> int:
    return _real_datetime.fromtimestamp(ts).hour


def _is_quiet(ts: float) -> bool:
    hour = _hour(ts)
    return hour >= QUIET_START or hour < QUIET_END


def _normalize(text: str) -> str:
    return re.sub(r"[\d\W_]+", " ", text.lower()).strip()


# ------------------------------------------------------------------ engine
def _build_engine(clock: SimClock, llm, tmp: str, seed: int):
    from core.agent_state import AgentState, StateMachine
    from core.chat_spool import ChatSpool
    from core.engine.autonomous import AutonomousController
    from core.engine.autonomous_pacing import AutonomousPacer
    from core.engine.cognitive_engine import CognitiveEngine
    from core.engine.interaction import InteractionController
    from core.engine.lingering_thought import LingeringThought
    from core.engine.memory_ops import MemoryOperationsController
    from core.engine.perception import PerceptionController
    from core.self_model import SelfModel
    from core.value_system import ValueSystem
    from core.world_graph import WorldGraph
    from config import Config

    engine = CognitiveEngine.__new__(CognitiveEngine)
    engine.memory = SimMemory(clock)
    engine.ego = SelfModel(memory_manager=None)
    engine.llm = llm
    engine.embedder = SimpleNamespace(encode=lambda text: [0.0])
    engine.short_term_buffer = []
    engine.stm_lock = threading.Lock()
    engine.lingering_thought = LingeringThought()
    from core.engine.life_log import LifeLog
    from core.prospective_memory import ProspectiveMemory

    engine.life_log = LifeLog()
    engine.prospective = ProspectiveMemory(os.path.join(tmp, "prospective.json"))
    from core.relationship import InsideJokes

    engine.inside_jokes = InsideJokes(os.path.join(tmp, "inside_jokes.json"))
    engine.stm_file_path = Config.STM_FILE
    engine.last_interaction_time = clock.time()
    engine.state_machine = StateMachine(AgentState.IDLE)
    engine._state_duration_checkpoint = engine.state_machine.duration_totals()
    engine._runtime_mutation_gate = threading.Lock()
    engine._interaction_state_lock = threading.Lock()
    engine._interaction_state_owner = None
    engine.event_journal = None
    engine.discord_bridge = None
    engine.reader = SimReader()
    engine.world_graph = WorldGraph(os.path.join(tmp, "world_graph.json"))
    engine.value_system = ValueSystem(os.path.join(tmp, "values.json"))
    engine.local_perception = SimPerception()
    engine.skills = SimpleNamespace(
        get_prompt_instructions=lambda *a, **k: "",
        execute=lambda *a, **k: "ok",
    )
    engine._dump_mind_state = lambda *a, **k: None

    memory_ops = object.__new__(MemoryOperationsController)
    memory_ops.engine = engine
    memory_ops.integrity_filter = SimpleNamespace(
        check_contradiction=lambda *a, **k: {"conflict": False, "reason": "", "impact_multiplier": 1.0},
        evaluate_input=lambda *a, **k: {"conflict": False, "reason": "", "impact_multiplier": 1.0},
    )
    memory_ops.slm_trainer = None
    memory_ops.save_short_term_memory = lambda: None
    memory_ops.apply_recall_effects = lambda *a, **k: None
    engine.memory_ops = memory_ops
    engine.perception_ops = PerceptionController(engine)
    engine.interaction = InteractionController(engine)

    controller = AutonomousController(engine)
    controller._pacer = AutonomousPacer(rng=random.Random(seed).random)
    controller._proactive_spool = ChatSpool(os.path.join(tmp, "proactive"), "response")
    engine.autonomous = controller
    return engine


@contextlib.contextmanager
def _sim_environment(clock: SimClock, tmp: str):
    from config import Config

    paths = {
        "EGO_STATE_FILE": os.path.join(tmp, "ego_state.json"),
        "STM_FILE": os.path.join(tmp, "short_term.json"),
        "WORLD_GRAPH_FILE": os.path.join(tmp, "world_graph.json"),
        "VALUES_FILE": os.path.join(tmp, "values.json"),
        "CHROMA_DB_PATH": os.path.join(tmp, "chroma"),
        "SLM_FINETUNE_QUEUE_FILE": os.path.join(tmp, "slm.txt"),
        "CHAT_PROACTIVE_SPOOL_DIR": os.path.join(tmp, "proactive"),
    }
    proxy = _TimeProxy(clock)
    sim_datetime = _datetime_for(clock)
    cwd = os.getcwd()
    with contextlib.ExitStack() as stack:
        for name, value in paths.items():
            if hasattr(Config, name):
                stack.enter_context(patch.object(Config, name, value))
        import importlib

        for module_name in _TIME_MODULES:
            module = importlib.import_module(module_name)
            stack.enter_context(patch.object(module, "time", proxy))
        for module_name in _DATETIME_MODULES:
            module = importlib.import_module(module_name)
            stack.enter_context(patch.object(module, "datetime", sim_datetime))
        stack.enter_context(patch("builtins.print"))
        import sys as _sys

        stack.enter_context(patch.dict(_sys.modules, {"psutil": SimpleNamespace(
            cpu_percent=lambda *a, **k: 10.0,
            virtual_memory=lambda: SimpleNamespace(percent=40.0),
        )}))
        import logging

        logging.disable(logging.CRITICAL)
        stack.callback(logging.disable, logging.NOTSET)
        os.chdir(tmp)
        stack.callback(os.chdir, cwd)
        yield


# ------------------------------------------------------------------- run
def run_week(
    *,
    seed: int = 7,
    days: int = 7,
    script: tuple[UserMessage, ...] = DEFAULT_SCRIPT,
    llm=None,
    start: float = DEFAULT_START,
    defer_replies: bool = False,
    llm_factory=None,
) -> SimReport:
    """``llm_factory(engine) -> llm`` plugs in a real model (built after the
    engine so it can read the ego for bio-throttling); otherwise ScriptedLLM."""
    # Global random drives bio jitter and small rolls; restore it afterwards so
    # a simulation never changes the randomness of its caller.
    saved_random = random.getstate()
    random.seed(seed)
    clock = SimClock(start)
    llm = llm or ScriptedLLM()
    try:
        # Logging may keep a file open inside tmp on Windows.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp, _sim_environment(clock, tmp):
            engine = _build_engine(clock, llm, tmp, seed)
            if llm_factory is not None:
                llm = llm_factory(engine)
            llm = PromptRecorder(llm)
            engine.llm = llm
            from config import Config

            with patch.object(Config, "DEFER_REPLIES_WHILE_ASLEEP", defer_replies):
                return asyncio.run(_simulate(engine, clock, llm, script, days, seed))
    finally:
        random.setstate(saved_random)


async def _simulate(engine, clock, llm, script, days, seed) -> SimReport:
    controller = engine.autonomous
    stats = [DayStats(day=d) for d in range(days)]
    day_start = _real_datetime.fromtimestamp(clock.start).replace(hour=0, minute=0)
    aura_messages: list[tuple[float, str, str, str]] = []  # (ts, stamp, kind, text)
    ping_times: list[float] = []
    busy_pings = [0]
    failed_turns: list = []
    friction_trace: list = []
    boredom_max = [0.0]
    identity_by_night: list[str] = []
    pending_by_night: list[str] = []
    sleep_times: list[str] = []

    def day_of(ts):
        return int((ts - day_start.timestamp()) // 86400)

    def stamp():
        return _real_datetime.fromtimestamp(clock.time()).strftime("%a %H:%M")

    original_deliver = controller._deliver_proactive

    def recording_deliver(text, label):
        sent = original_deliver(text, label)
        if sent:
            d = day_of(clock.time())
            if 0 <= d < days:
                stats[d].pings += 1
                stats[d].quiet_hour_pings += int(_is_quiet(clock.time()))
            ping_times.append(clock.time())
            if engine.prospective.is_busy(clock.time()):
                busy_pings[0] += 1
            aura_messages.append((clock.time(), stamp(), label, text))
        return sent

    controller._deliver_proactive = recording_deliver

    memory_ops = engine.memory_ops

    def sim_sleep():
        reflected_before = getattr(engine.ego, "last_identity_reflection", 0.0)
        memory_ops._commit_sleep_homeostasis(clock.time())
        memory_ops._identity_evolution_phase()
        engine.ego.reroll_thresholds()
        if getattr(engine.ego, "last_identity_reflection", 0.0) != reflected_before:
            identity_by_night.append(engine.ego.evolved_insight)
            pending_by_night.append(getattr(engine.ego, "pending_identity_insight", ""))

    memory_ops.sleep = sim_sleep

    from core.engine import sleep_cycle

    original_begin_sleep = sleep_cycle.begin_sleep

    def recording_begin_sleep(ego, now, *, nap, run_maintenance, rng=random):
        until = original_begin_sleep(ego, now, nap=nap, run_maintenance=run_maintenance, rng=rng)
        d = day_of(now)
        if 0 <= d < days:
            stats[d].sleeps += 1
            stats[d].naps += int(nap)
        fmt = "%a %H:%M"
        sleep_times.append(
            f"{_real_datetime.fromtimestamp(now).strftime(fmt)} -> "
            f"{_real_datetime.fromtimestamp(until).strftime(fmt)} ({'ngủ trưa' if nap else 'đêm'})"
        )
        return until

    sleep_cycle.begin_sleep = recording_begin_sleep

    original_reading = controller._do_reading_session

    def recording_reading():
        original_reading()
        d = day_of(clock.time())
        if 0 <= d < days and controller._last_reading_succeeded:
            stats[d].readings += 1

    controller._do_reading_session = recording_reading

    original_anxiety = controller._separation_anxiety

    def recording_anxiety(stage, idle_time):
        d = day_of(clock.time())
        if 0 <= d < days:
            stats[d].anxiety_stages += 1
        return original_anxiety(stage, idle_time)

    controller._separation_anxiety = recording_anxiety

    from config import Config
    from core.engine.life_log import note_message_received

    arrived: list[str] = []
    waiting: list = []
    pending_script = sorted(
        script,
        key=lambda m: (m.day, m.hour, m.minute),
    )
    bio_fields = ("mood", "stress", "fatigue", "energy", "social_need", "curiosity", "dopamine_level")
    ranges = {name: [math.inf, -math.inf] for name in bio_fields}
    non_finite: set[str] = set()
    end = day_start.timestamp() + days * 86400
    last_mono = clock.monotonic()

    while clock.time() < end:
        clock.advance(STEP_SECONDS)
        now = clock.time()

        handled_message = False
        while pending_script:
            msg = pending_script[0]
            due = day_start.replace(hour=msg.hour, minute=msg.minute).timestamp() + msg.day * 86400
            if due > now:
                break
            pending_script.pop(0)
            request_id = f"sim-{len(arrived)}"
            arrived.append(request_id)
            note_message_received(engine, request_id, due)
            waiting.append((msg, request_id))
        ready = []
        for item in list(waiting):
            if sleep_cycle.should_defer_message(
                engine.ego, item[0].text, now, Config.DEFER_REPLIES_WHILE_ASLEEP
            ):
                continue
            waiting.remove(item)
            ready.append(item)
        for msg, request_id in ready:
            handled_message = True
            engine.last_interaction_time = now
            try:
                result = engine.interaction.interaction_loop(msg.text, request_id=request_id)
            except Exception as error:  # a real model may time out or misbehave
                failed_turns.append((stamp(), type(error).__name__))
                result = None
            engine.last_interaction_time = clock.time()
            stats[msg.day].user_messages += 1
            friction_trace.append(
                (stamp(), round(float(getattr(engine.ego, "relational_friction", 0.0) or 0.0), 2))
            )
            if isinstance(result, dict) and result.get("response"):
                stats[msg.day].replies += 1
                if result.get("collapsed"):
                    stats[msg.day].collapses += 1
                aura_messages.append((clock.time(), stamp(), "reply", result["response"]))

        engine.cognitive_tick(STEP_SECONDS)
        mono = clock.monotonic()
        # As in production: no proactive action in the iteration that just
        # answered the owner (the pacer still sees the elapsed time later).
        if not handled_message:
            try:
                await controller._run_autonomous_decisions(mono, mono - last_mono)
            except Exception as error:
                failed_turns.append((stamp(), f"autonomous:{type(error).__name__}"))
            last_mono = mono

        d = day_of(now)
        if 0 <= d < days:
            stats[d]._mood_samples.append(float(engine.ego.mood))
            stats[d].fatigue_max = max(stats[d].fatigue_max, round(float(engine.ego.fatigue), 3))
        boredom_max[0] = max(boredom_max[0], float(getattr(engine.ego, "boredom", 0.0) or 0.0))
        if int(now) % 3600 < STEP_SECONDS:
            for name in bio_fields:
                value = getattr(engine.ego, name, None)
                if not isinstance(value, (int, float)):
                    continue
                if not math.isfinite(value):
                    non_finite.add(name)
                    continue
                ranges[name][0] = min(ranges[name][0], value)
                ranges[name][1] = max(ranges[name][1], value)

    sleep_cycle.begin_sleep = original_begin_sleep
    extra = {
        "pings_while_owner_busy": busy_pings[0],
        "recap_turns": llm.recap_turns,
        "open_loops_remembered": len(engine.prospective.items),
        "prompt_markers": dict(llm.markers),
        "llm_calls": llm.calls,
        "llm_failures": llm.failures,
        "llm_seconds": round(llm.seconds, 1),
        "failed_turns": failed_turns,
        "friction_after_message": friction_trace,
        "inside_jokes": len(engine.inside_jokes.jokes),
        "assistant_injected": getattr(llm.inner, "assistant_injected", 0),
        "boredom_max": round(boredom_max[0], 3),
        "reading_feelings": [
            round(t.valence, 2) for t in engine.memory.traces if getattr(t, "origin_kind", "") == "reading"
        ],
    }
    return _build_report(
        seed, stats, ranges, non_finite, ping_times, identity_by_night,
        pending_by_night, aura_messages, engine, script, day_start, sleep_times,
        extra,
    )


def _silence_windows(script, day_start):
    times = sorted(
        day_start.replace(hour=m.hour, minute=m.minute).timestamp() + m.day * 86400
        for m in script
    )
    return [(a, b) for a, b in zip(times, times[1:]) if b - a > 12 * 3600]


def _build_report(seed, stats, ranges, non_finite, ping_times, identity_by_night,
                  pending_by_night, aura_messages, engine, script, day_start,
                  sleep_times, extra) -> SimReport:
    from core import identity_drift
    from core.message_bubbles import flatten_bubbles

    for day in stats:
        if day._mood_samples:
            day.mood_mean = round(sum(day._mood_samples) / len(day._mood_samples), 3)
    gaps = []
    for a, b in _silence_windows(script, day_start):
        inside = [t for t in ping_times if a < t < b]
        gaps.extend(round((y - x) / 3600, 2) for x, y in zip(inside, inside[1:]))

    texts = [flatten_bubbles(text) for _, _, _, text in aura_messages]
    normalized = [_normalize(t) for t in texts]
    repeated = sum(1 for i, t in enumerate(normalized) if t and t in normalized[:i])
    # A message "leaks" assistant register if the style filter would still
    # change it (cliché, markdown, list or internal jargon) — same rules.
    from core.style_filter import humanize

    leak_kinds = {"cliche", "markdown", "list", "jargon"}
    assistant = sum(1 for t in texts if humanize(t)[1] & leak_kinds)
    # Verbal tics: a message sharing any 4-word phrase with an earlier one.
    seen_phrases: set = set()
    phrase_repeats = 0
    for t in normalized:
        words = t.split()
        grams = {" ".join(words[i:i + 4]) for i in range(len(words) - 3)}
        if grams & seen_phrases:
            phrase_repeats += 1
        seen_phrases |= grams
    refusals = sum(
        1 for t in texts if any(re.search(p, t, re.IGNORECASE) for p in _REFUSAL_PATTERNS)
    )
    total = max(1, len(texts))

    # Did Aura herself bring the topic back up after the day it was raised?
    follow_ups = {}
    for keyword, raised_day in OPEN_LOOPS:
        raised_at = day_start.timestamp() + (raised_day + 1) * 86400
        follow_ups[keyword] = any(
            keyword in flatten_bubbles(text).lower()
            for ts, _, _, text in aura_messages
            if ts >= raised_at
        )

    with engine.stm_lock:
        stm = list(engine.short_term_buffer)
    leaks = sum(1 for line in stm if "[send]" in line.lower())

    drift = [
        round(1.0 - identity_drift.similarity(a, b), 3)
        for a, b in zip(identity_by_night, identity_by_night[1:])
    ]
    return SimReport(
        seed=seed,
        days=stats,
        bio_ranges={k: (round(v[0], 3), round(v[1], 3)) for k, v in ranges.items() if v[0] <= v[1]},
        non_finite_fields=sorted(non_finite),
        ping_gaps_in_silence_hours=gaps,
        identity_by_night=identity_by_night,
        pending_by_night=pending_by_night,
        identity_drift=drift,
        repetition_rate=round(repeated / total, 3),
        phrase_repetition_rate=round(phrase_repeats / total, 3),
        assistant_phrase_rate=round(assistant / total, 3),
        refusal_rate=round(refusals / total, 3),
        open_loop_follow_ups=follow_ups,
        send_tag_leaks=leaks,
        sleep_times=sleep_times,
        aura_messages=aura_messages,
        **extra,
    )


def format_report(report: SimReport) -> str:
    lines = [f"Aura — mô phỏng {len(report.days)} ngày (seed={report.seed})", ""]
    lines.append(
        "ngày | tin user | trả lời | gục | ping | ping giờ ngủ | ngủ (trưa) | đọc | lo âu | mood tb | fatigue max"
    )
    for d in report.days:
        lines.append(
            f"{d.day:>4} | {d.user_messages:>8} | {d.replies:>7} | {d.collapses:>3} | {d.pings:>4} | "
            f"{d.quiet_hour_pings:>12} | {d.sleeps:>4} ({d.naps}) | {d.readings:>3} | {d.anxiety_stages:>5} | "
            f"{d.mood_mean:>7.2f} | {d.fatigue_max:>11.2f}"
        )
    lines += [
        "",
        "Các giấc ngủ:",
        *[f"  {line}" for line in report.sleep_times],
        f"Khoảng cách giữa các ping lúc bị bỏ rơi (giờ): {report.ping_gaps_in_silence_hours}",
        f"Biên độ sinh học: {report.bio_ranges}",
        f"Trường không hữu hạn: {report.non_finite_fields or 'không có'}",
        f"Số lần phản tư bản ngã: {len(report.identity_by_night)}",
        f"Trôi bản ngã giữa các đêm (0=giữ nguyên, 1=đổi hẳn): {report.identity_drift}",
        f"Bản ngã đang chờ xác nhận theo đêm: {[p[:30] for p in report.pending_by_night]}",
        f"LLM lỡ giọng trợ lý {report.assistant_injected} lần -> còn lọt sau bộ lọc: {report.assistant_phrase_rate}",
        f"Tỉ lệ lặp nguyên câu: {report.repetition_rate} | lặp cụm từ: {report.phrase_repetition_rate} "
        f"| giọng trợ lý: {report.assistant_phrase_rate} "
        f"| từ chối: {report.refusal_rate}",
        f"Hỏi lại chuyện dang dở: {report.open_loop_follow_ups} "
        f"(đã ghi nhớ {report.open_loops_remembered} chuyện)",
        f"Ping lúc người dùng đang bận: {report.pings_while_owner_busy}",
        f"Lượt trả lời có 'từ lần cuối nói chuyện': {report.recap_turns}",
        f"Dấu hiệu trong prompt: {report.prompt_markers}",
        f"Khúc mắc sau mỗi tin (từ thứ Sáu): {[f for f in report.friction_after_message if f[0][:3] in ('Fri', 'Sat')]}",
        f"Trò đùa riêng đã nhớ: {report.inside_jokes}",
        f"Chán cao nhất: {report.boredom_max} | cảm xúc khi đọc sách: {report.reading_feelings}",
        f"Thẻ [SEND] lọt vào STM: {report.send_tag_leaks}",
        f"LLM: {report.llm_calls} lần gọi, {report.llm_failures} lỗi, {report.llm_seconds}s; "
        f"lượt hỏng: {report.failed_turns or 'không có'}",
    ]
    return "\n".join(lines)
