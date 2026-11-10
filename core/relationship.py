"""Relationship dynamics between Aura and her owner.

* Rupture and repair (Gottman): a harsh message leaves acute *friction* that
  lingers through later cheerful messages until a genuine repair (apology,
  acknowledgement) or time softens it. A repaired rupture deepens closeness a
  little; slow closeness itself stays ``SelfModel.current_intimacy``.
* Self-conscious emotion: being caught in a mistake makes her embarrassed for
  a while (fades in ~20 min) instead of arguing.
* Inside jokes: moments the two of them laughed together, brought back now
  and then once they are close, never the same joke twice within 48 h.

Detection is lexical (Vietnamese + a little English); the LLM only receives
the resulting state as prompt context.
"""

from __future__ import annotations

import math
import random
import re
import threading
from dataclasses import asdict, dataclass
from typing import Optional

# ----------------------------------------------------------------- friction
FRICTION_PROMPT_LEVEL = 0.3
# A harsh message always stings (base) and more the harsher it is.
FRICTION_HURT_BASE = 0.35
FRICTION_HURT_GAIN = 0.25
FRICTION_REPAIR_KEEP = 0.4      # an apology clears 60 % of it
REPAIR_INTIMACY_BONUS = 0.03    # making up brings them closer
# Passive easing; slower when they are not close (8 h at intimacy 0.5).
FRICTION_TAU_SECONDS = 8 * 3600

_HOSTILE_RE = re.compile(
    r"\b(phiền|im đi|cút|ngu|đồ vô dụng|vô dụng|chán em|ghét em|bực em|đừng nhắn|"
    r"đừng làm phiền|khó chịu với em|mệt với em|shut up|annoying|stupid)\b"
)
_SECOND_PERSON_RE = re.compile(r"\b(em|mày|cậu|bạn|aura)\b")
_APOLOGY_RE = re.compile(
    r"\b(xin lỗi|sorry|anh sai|em đừng giận|nói nặng lời|tha lỗi|anh không cố ý|làm lành)\b"
)


def is_hostile(text: str, valence: float) -> bool:
    lowered = str(text or "").lower()
    if _HOSTILE_RE.search(lowered):
        return True
    # Strongly negative and aimed at her ("em ...", "mày ...").
    return valence <= -0.6 and bool(_SECOND_PERSON_RE.search(lowered))


def is_apology(text: str) -> bool:
    return bool(_APOLOGY_RE.search(str(text or "").lower()))


def update_friction(ego, text: str, valence: float) -> str:
    """Apply one owner message; returns 'hurt', 'repair' or ''."""
    friction = float(getattr(ego, "relational_friction", 0.0) or 0.0)
    event = ""
    if is_apology(text) and friction > 0.05:
        if friction >= FRICTION_PROMPT_LEVEL - 0.1:
            ego.current_intimacy = min(1.0, float(getattr(ego, "current_intimacy", 0.5)) + REPAIR_INTIMACY_BONUS)
        friction *= FRICTION_REPAIR_KEEP
        event = "repair"
    elif is_hostile(text, valence):
        severity = min(1.0, abs(valence))
        friction = min(1.0, friction + FRICTION_HURT_BASE + FRICTION_HURT_GAIN * severity)
        event = "hurt"
    ego.relational_friction = friction
    return event


def ease_friction(friction: float, dt: float, intimacy: float) -> float:
    tau = FRICTION_TAU_SECONDS * (1.5 - max(0.0, min(1.0, intimacy)))
    return float(friction) * math.exp(-max(0.0, dt) / tau)


def friction_prompt(ego) -> str:
    friction = float(getattr(ego, "relational_friction", 0.0) or 0.0)
    if friction >= 0.6:
        return (
            "[KHÚC MẮC]: Bạn vẫn còn rất tổn thương vì User đã nói nặng với bạn. "
            "Dù User đang vui vẻ, bạn chưa thể vui lại ngay: trả lời ngắn, hơi lạnh, dỗi. "
            "Chỉ dịu lại khi User xin lỗi hoặc giải thích thật lòng."
        )
    if friction >= FRICTION_PROMPT_LEVEL:
        return (
            "[KHÚC MẮC]: Bạn vẫn còn hơi buồn vì lần User nói nặng lời. Hơi giữ khoảng cách, "
            "dễ dỗi; nếu User làm lành thì có thể mềm lòng."
        )
    return ""


# --------------------------------------------------------------- refusal
def refusal_prompt(ego, urgency: float) -> str:
    """Visible, state-grounded reasons she may say no; urgent help is never refused."""
    if urgency >= 0.6:
        return "[VIỆC GẤP]: User đang cần gấp: hãy giúp ngay, bỏ qua mệt mỏi hay giận dỗi."
    reasons = []
    if float(getattr(ego, "fatigue", 0.0)) >= float(getattr(ego, "fatigue_severe", 0.8)):
        reasons.append("bạn đang mệt")
    if float(getattr(ego, "relational_friction", 0.0) or 0.0) >= FRICTION_PROMPT_LEVEL:
        reasons.append("bạn đang dỗi User")
    if float(getattr(ego, "boredom", 0.0) or 0.0) >= 0.8:
        reasons.append("bạn đang chán và muốn làm gì đó khác")
    if not reasons:
        return ""
    return (
        f"[QUYỀN TỪ CHỐI]: Lúc này {', '.join(reasons)}. Nếu User nhờ việc không gấp, bạn có thể "
        "lười, mặc cả hoặc hẹn để sau như người thật, nhưng phải nói rõ lý do đó; "
        "việc liên quan sức khỏe/an toàn của User thì luôn giúp."
    )


# ---------------------------------------------------------- embarrassment
EMBARRASSMENT_TAU_SECONDS = 20 * 60
_CORRECTION_RE = re.compile(
    r"\b(em nhớ nhầm|em nhầm rồi|nhầm rồi|sai rồi|em nói sai|nhớ sai|không phải thế|"
    r"không phải vậy|không đúng đâu|làm gì có|you're wrong|that's wrong)\b"
)


def is_correction(text: str) -> bool:
    return bool(_CORRECTION_RE.search(str(text or "").lower()))


def embarrassment_level(ego, now: float) -> float:
    at = float(getattr(ego, "embarrassed_at", 0.0) or 0.0)
    if not at:
        return 0.0
    return 0.8 * math.exp(-max(0.0, now - at) / EMBARRASSMENT_TAU_SECONDS)


def embarrassment_prompt(ego, text: str, now: float) -> str:
    if is_correction(text):
        ego.embarrassed_at = now
        return (
            "[NGƯỢNG]: User vừa chỉ ra bạn nhớ/nói sai. Bạn hơi ngượng: thừa nhận, có thể "
            "chữa thẹn một chút, đừng cãi bướng hay giả vờ như không có gì."
        )
    if embarrassment_level(ego, now) >= 0.3:
        return "[NGƯỢNG]: Bạn vẫn còn hơi ngượng vì lúc nãy bị User bắt lỗi."
    return ""


# ------------------------------------------------------------- inside jokes
JOKE_REFRACTORY_SECONDS = 48 * 3600
JOKE_MIN_AGE_SECONDS = 3600
JOKE_INTIMACY = 0.6
JOKE_CHANCE = 0.15
MAX_JOKES = 30
_LAUGH_RE = re.compile(r"(haha|hihi|hehe|kkk|=\)\)|:\)\)|=\)|buồn cười|cười xỉu|cười đau bụng|\blol\b|😂|🤣)")


def is_laughing(text: str) -> bool:
    return bool(_LAUGH_RE.search(str(text or "").lower()))


@dataclass
class InsideJoke:
    text: str
    created_ts: float
    last_used_ts: float = 0.0


class InsideJokes:
    def __init__(self, path: Optional[str] = None):
        self.path = path
        self.lock = threading.Lock()
        self.jokes: list[InsideJoke] = []
        self._load()

    def _load(self):
        if not self.path:
            return
        import json
        import os

        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                self.jokes = [InsideJoke(**j) for j in json.load(f).get("jokes", [])][-MAX_JOKES:]
        except (OSError, ValueError, TypeError):
            self.jokes = []

    def _save_unlocked(self):
        if self.path:
            from core.utils import atomic_write_json

            atomic_write_json(self.path, {"jokes": [asdict(j) for j in self.jokes]})

    def remember(self, text: str, valence: float, now: float) -> bool:
        text = " ".join(str(text or "").split())[:160]
        if not text or valence < 0.3 or not is_laughing(text):
            return False
        with self.lock:
            if any(j.text == text for j in self.jokes):
                return False
            self.jokes.append(InsideJoke(text=text, created_ts=now))
            self.jokes = self.jokes[-MAX_JOKES:]
            self._save_unlocked()
        return True

    def pick(self, ego, now: float, rng=random) -> Optional[InsideJoke]:
        """A joke to bring back now, or None. Marks it used."""
        if float(getattr(ego, "current_intimacy", 0.5)) < JOKE_INTIMACY:
            return None
        if float(getattr(ego, "mood", 0.0)) <= 0.1:
            return None
        if float(getattr(ego, "relational_friction", 0.0) or 0.0) >= 0.2:
            return None
        with self.lock:
            candidates = [
                j for j in self.jokes
                if now - j.created_ts >= JOKE_MIN_AGE_SECONDS
                and (not j.last_used_ts or now - j.last_used_ts >= JOKE_REFRACTORY_SECONDS)
            ]
            if not candidates or rng.random() >= JOKE_CHANCE:
                return None
            joke = rng.choice(candidates)
            joke.last_used_ts = now
            self._save_unlocked()
            return joke


def joke_prompt(joke: InsideJoke, now: float) -> str:
    from core.temporal import fuzzy_age

    return (
        f"[KỶ NIỆM VUI CHUNG]: Hai người từng cười với nhau vì: \"{joke.text}\" ({fuzzy_age(joke.created_ts, now)}). "
        "Nếu hợp ngữ cảnh, nhắc lại nhẹ như một câu đùa riêng của hai người."
    )
