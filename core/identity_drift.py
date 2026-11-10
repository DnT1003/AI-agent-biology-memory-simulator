"""Guard against one evening rewriting Aura's whole identity.

Nightly reflection proposes a new self-description. People revise who they
are slowly: a small revision is adopted at once, while a drastic one is only
adopted when the next night's reflection points the same way.
"""

import re

DEFAULT_INSIGHT = "Tôi đang trong quá trình định hình bản sắc."
# Word-overlap (Jaccard) at or above this counts as "the same self, revised".
MIN_SIMILARITY = 0.3
# Reflect on who you are at most once per night, not at every nap.
MIN_REFLECTION_GAP_SECONDS = 16 * 3600

_WORD_RE = re.compile(r"\w+", re.UNICODE)


def similarity(a: str, b: str) -> float:
    words_a = set(_WORD_RE.findall(str(a or "").lower()))
    words_b = set(_WORD_RE.findall(str(b or "").lower()))
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / len(words_a | words_b)


def decide(previous: str, candidate: str, pending: str):
    """Return ``(adopt, new_pending)`` for tonight's candidate insight."""
    previous = (previous or "").strip()
    if not previous or previous == DEFAULT_INSIGHT:
        return True, ""  # identity not formed yet: the first reflection forms it
    if similarity(previous, candidate) >= MIN_SIMILARITY:
        return True, ""
    if pending and similarity(pending, candidate) >= MIN_SIMILARITY:
        return True, ""  # second night in a row pointing the same way
    return False, candidate
