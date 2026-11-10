"""A thought that is still "on her mind" and may slip into the conversation.

Replaces the old per-message 5% "intrusive thought" roll, which invented
unrelated content (cravings, random embarrassment). Here the content is always
real: the memory Aura was just mind-wandering about, or the chapter she just
read. The chance of blurting it out fades with the thought's age, so it is
time-based rather than per-call, and each thought surfaces at most once.
"""

import math
import random
import threading

# Chance to mention a brand-new thought in the next message.
SURFACE_PEAK = 0.3
# The urge fades with this time constant (seconds).
FADE_SECONDS = 20 * 60
# Older than this, the thought is simply gone.
MAX_AGE_SECONDS = 2 * 3600
_MAX_CHARS = 200


class LingeringThought:
    def __init__(self):
        self._lock = threading.Lock()
        self._content = None
        self._at = 0.0

    def set(self, content: str, now: float) -> None:
        content = " ".join(str(content or "").split())
        if not content:
            return
        with self._lock:
            self._content = content[:_MAX_CHARS]
            self._at = float(now)

    def surface_probability(self, now: float) -> float:
        with self._lock:
            if self._content is None:
                return 0.0
            age = max(0.0, float(now) - self._at)
        if age > MAX_AGE_SECONDS:
            return 0.0
        return SURFACE_PEAK * math.exp(-age / FADE_SECONDS)

    def maybe_surface(self, now: float, rng=random):
        """Return the thought (consuming it) if it slips out now, else None."""
        p = self.surface_probability(now)
        with self._lock:
            if self._content is None:
                return None
            if max(0.0, float(now) - self._at) > MAX_AGE_SECONDS:
                self._content = None
                return None
            if rng.random() >= p:
                return None
            content, self._content = self._content, None
            return content


def lingering_thought_of(engine) -> LingeringThought:
    thought = getattr(engine, "lingering_thought", None)
    if not isinstance(thought, LingeringThought):
        thought = LingeringThought()
        engine.lingering_thought = thought
    return thought
