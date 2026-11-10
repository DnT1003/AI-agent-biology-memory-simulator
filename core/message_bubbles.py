"""Chat "bubbles": the LLM marks message breaks with ``[SEND]``.

The tag is a transport instruction, never message text. Transports that can
send several messages (Discord, web dashboard) split on it; everything that
stores or prints a single text (CLI, short-term memory) flattens it.
"""

import random
import re

# Tolerates the casing/spacing variants LLMs produce: [SEND], [ send ], [Send].
_SEND_TAG_RE = re.compile(r"\s*\[\s*send\s*\]\s*", re.IGNORECASE)

# Typing speed of a casual phone/keyboard chatter, characters per second.
_BASE_CHARS_PER_SECOND = 18.0
MIN_TYPING_DELAY = 0.5
MAX_TYPING_DELAY = 6.0


def split_bubbles(text: str) -> list[str]:
    """Return the non-empty message chunks of ``text`` in order."""
    if not isinstance(text, str):
        return []
    return [chunk.strip() for chunk in _SEND_TAG_RE.split(text) if chunk.strip()]


def flatten_bubbles(text: str) -> str:
    """Single-text form of a response: bubbles joined by newlines."""
    if not isinstance(text, str):
        return text
    return "\n".join(split_bubbles(text))


def typing_delay(chunk: str, fatigue: float = 0.0, arousal: float = 0.0, rng=random) -> float:
    """Seconds a person would take to type ``chunk``.

    Tired fingers are slower, excitement types faster; a short pause before
    starting is always there. Bounded so a long bubble never stalls a chat.
    """
    fatigue = min(1.0, max(0.0, float(fatigue or 0.0)))
    arousal = min(1.0, max(0.0, float(arousal or 0.0)))
    speed = _BASE_CHARS_PER_SECOND * (1.0 - 0.5 * fatigue + 0.3 * arousal)
    delay = len(chunk) / speed + rng.uniform(0.3, 0.9)
    return min(MAX_TYPING_DELAY, max(MIN_TYPING_DELAY, delay))
