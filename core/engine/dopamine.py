"""Reward-prediction-error dopamine model.

Dopamine reacts to rewards that are *better than expected*, not to rewards as
such. Each event type keeps a learned expectation, so a reward that repeats
habituates (its prediction error shrinks), and a reward that is expected but
missing produces a dip. Pure functions only: SelfModel owns state and locking.

State (all persisted by SelfModel):
- ``dopamine_level``     what prompts and behaviour read (baseline + burst)
- ``dopamine_baseline``  tonic level, drifts with mood over hours
- ``reward_expectations`` per-event learned expectation in [-1, 1]
- ``dopamine_receptors``  sensitivity; drops under sustained high dopamine
"""

import math

REWARD_EVENTS = frozenset({
    "user_message",   # valence of the user's message (warmth is rewarding)
    "reunion",        # the user returns after a long absence
    "ping_answered",  # a proactive message got a reply
    "ping_ignored",   # a proactive message got no reply
    "reading",        # read the next part of a real book
    "new_book",       # started a book never read before
    "tool_success",   # a user-requested tool succeeded
})

LEARNING_RATE = 0.1          # how fast expectations adapt (habituation)
BURST_GAIN = 0.3             # level change per unit of prediction error
MOOD_GAIN = 0.05             # small mood nudge per unit of prediction error
PHASIC_TAU_SECONDS = 15 * 60       # a burst fades over ~15 minutes
BASELINE_TAU_SECONDS = 6 * 3600    # tonic level follows mood over ~6 hours
BASELINE_SETPOINT = 0.5
BASELINE_MOOD_GAIN = 0.2
TOLERANCE_THRESHOLD = 0.7          # sustained level above this blunts receptors
TOLERANCE_RATE_PER_HOUR = 0.05
RECEPTOR_RECOVERY_PER_HOUR = 0.08
MIN_RECEPTORS = 0.1


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def prediction_error(expectations: dict, event: str, reward: float) -> tuple[float, dict]:
    """Return (delta, updated expectations) for one reward event."""
    if event not in REWARD_EVENTS:
        raise ValueError(f"unknown reward event: {event!r}")
    reward = _clamp(float(reward), -1.0, 1.0)
    expected = float(expectations.get(event, 0.0))
    delta = reward - expected
    updated = dict(expectations)
    updated[event] = _clamp(expected + LEARNING_RATE * delta, -1.0, 1.0)
    return delta, updated


def burst(level: float, delta: float, receptors: float) -> float:
    """Phasic response; blunted receptors weaken both bursts and dips."""
    return _clamp(level + BURST_GAIN * delta * receptors, 0.0, 1.0)


def mood_shift(delta: float) -> float:
    return MOOD_GAIN * delta


def relax(level: float, baseline: float, receptors: float, mood: float, dt_seconds: float):
    """Advance tonic/phasic dynamics and receptor tolerance by ``dt_seconds``.

    Returns (level, baseline, receptors).
    """
    if dt_seconds <= 0.0:
        return level, baseline, receptors
    target = _clamp(BASELINE_SETPOINT + BASELINE_MOOD_GAIN * mood, 0.0, 1.0)
    baseline = target + (baseline - target) * math.exp(-dt_seconds / BASELINE_TAU_SECONDS)
    level = baseline + (level - baseline) * math.exp(-dt_seconds / PHASIC_TAU_SECONDS)

    dt_hours = dt_seconds / 3600.0
    receptors += RECEPTOR_RECOVERY_PER_HOUR * (1.0 - receptors) * dt_hours
    if level > TOLERANCE_THRESHOLD:
        excess = (level - TOLERANCE_THRESHOLD) / (1.0 - TOLERANCE_THRESHOLD)
        receptors -= TOLERANCE_RATE_PER_HOUR * excess * dt_hours
    return _clamp(level, 0.0, 1.0), _clamp(baseline, 0.0, 1.0), _clamp(receptors, MIN_RECEPTORS, 1.0)


def motivation(level: float) -> float:
    """Behavioural drive multiplier: 0.5 (anhedonic) .. 1.5 (eager)."""
    return 0.5 + _clamp(level, 0.0, 1.0)
