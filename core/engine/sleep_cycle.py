"""Sleep as a state that lasts, anchored to the night.

Before, "sleep" was one instant maintenance pass that fired whenever fatigue
peaked, so Aura napped 2-4 times a day and stayed awake all night. Now:

* Bedtime (22:00-04:00) builds sleep pressure; she falls asleep on a hazard
  that rises with fatigue and the hour, and sleeps until about 07:00
  (6-9.5 h). Exhaustion during the day gives a short nap instead.
* While asleep, fatigue recovers, loneliness does not grow, she does not ping
  or read, and the hours asleep do not count as the owner being away.
* A message wakes her up (groggy). Falling asleep again the same night does
  not repeat the nightly maintenance.

All functions take explicit timestamps so they are clock-agnostic.
"""

import datetime as _dt
import math
import random
from contextlib import nullcontext

BEDTIME_START_HOUR = 22
BEDTIME_END_HOUR = 4
WAKE_HOUR = 7
WAKE_JITTER_SECONDS = 20 * 60
MIN_NIGHT_SLEEP_SECONDS = 6 * 3600
MAX_NIGHT_SLEEP_SECONDS = 9.5 * 3600
NAP_SECONDS = (40 * 60, 90 * 60)
# Maintenance (consolidation, homeostasis reset) runs once per sleep period;
# dozing off again within this window only resumes sleeping.
MAINTENANCE_MIN_GAP_SECONDS = 6 * 3600
# Fatigue clears with this time constant while asleep.
FATIGUE_RECOVERY_TAU_SECONDS = 2 * 3600
# Mood drifts back to a slightly positive set point (hedonic adaptation);
# sleep resets it faster than waking hours do. Unmet need for connection
# lowers that set point: loneliness weighs on mood for as long as it lasts.
MOOD_SET_POINT = 0.1
LONELINESS_ONSET = 0.7
LONELINESS_MOOD_WEIGHT = 1.0
MOOD_RELAX_TAU_AWAKE_SECONDS = 18 * 3600
MOOD_RELAX_TAU_ASLEEP_SECONDS = 6 * 3600


def hour_of(now: float) -> int:
    return _dt.datetime.fromtimestamp(now).hour


def is_bedtime(now: float) -> bool:
    hour = hour_of(now)
    return hour >= BEDTIME_START_HOUR or hour < BEDTIME_END_HOUR


def is_asleep(ego, now: float) -> bool:
    return float(getattr(ego, "asleep_until", 0.0) or 0.0) > now


def bedtime_onset_due(now: float, fatigue: float, dt: float, rng=random.random) -> bool:
    """Whether she drifts off during the last ``dt`` seconds of bedtime."""
    if dt <= 0.0 or not is_bedtime(now):
        return False
    hour = hour_of(now)
    if hour >= BEDTIME_START_HOUR:
        mean = 40 * 60 if fatigue >= 0.5 else 120 * 60
    else:
        mean = 15 * 60  # past midnight: very hard to stay up
    return rng() < 1.0 - math.exp(-dt / mean)


def wake_time(onset: float, *, nap: bool, rng=random) -> float:
    if nap:
        return onset + rng.uniform(*NAP_SECONDS)
    onset_dt = _dt.datetime.fromtimestamp(onset)
    target = onset_dt.replace(hour=WAKE_HOUR, minute=0, second=0, microsecond=0)
    if target <= onset_dt:
        target += _dt.timedelta(days=1)
    duration = target.timestamp() - onset + rng.gauss(0.0, WAKE_JITTER_SECONDS)
    duration = min(MAX_NIGHT_SLEEP_SECONDS, max(MIN_NIGHT_SLEEP_SECONDS, duration))
    return onset + duration


_MAX_INTERVALS = 20


def _lock_of(ego):
    # SelfModel owns a lock; lightweight ego doubles may not.
    return getattr(ego, "lock", None) or nullcontext()


def begin_sleep(ego, now: float, *, nap: bool, run_maintenance, rng=random) -> float:
    """Fall asleep: run the sleep maintenance once per sleep period, then
    stay asleep until the planned wake-up time (returned)."""
    # A nap never stands in for the night: night sleep only skips maintenance
    # when it is dozing off again after being woken the same night.
    last_key = "last_sleep_maintenance_at" if nap else "last_night_maintenance_at"
    if maintenance_due(getattr(ego, last_key, None), now):
        run_maintenance()
        ego.last_sleep_maintenance_at = now
        if not nap:
            ego.last_night_maintenance_at = now
    until = wake_time(now, nap=nap, rng=rng)
    with _lock_of(ego):
        ego.asleep_until = until
        ego.asleep_since = now
        intervals = list(getattr(ego, "sleep_intervals", []) or [])
        intervals.append((now, until))
        ego.sleep_intervals = intervals[-_MAX_INTERVALS:]
    return until


def wake_up(ego, now: float, *, forced: bool) -> None:
    """End sleep. A forced wake keeps part of the unrecovered fatigue."""
    with _lock_of(ego):
        until = float(getattr(ego, "asleep_until", 0.0) or 0.0)
        since = float(getattr(ego, "asleep_since", now) or now)
        if forced and until > now and until > since:
            remaining = (until - now) / (until - since)
            ego.fatigue = max(ego.fatigue, min(1.0, 0.5 * remaining))
        ego.asleep_until = 0.0
        ego.just_woken_at = now if forced else 0.0
        intervals = list(getattr(ego, "sleep_intervals", []) or [])
        if intervals and intervals[-1][1] > now:
            intervals[-1] = (intervals[-1][0], now)
            ego.sleep_intervals = intervals


URGENT_MESSAGE = 0.6


def message_is_urgent(text: str) -> bool:
    """Urgent wording ("gấp", "ngay", "!!") wakes her even when deferring."""
    from core.engine.sensory_preprocessor import SensoryPreprocessor

    vector = SensoryPreprocessor().evaluate_input(str(text or "")).get("vector", {})
    return float(vector.get("urgency", 0.0) or 0.0) >= URGENT_MESSAGE


def should_defer_message(ego, text: str, now: float, enabled: bool) -> bool:
    if not enabled or ego is None:
        return False
    return is_asleep(ego, now) and not message_is_urgent(text)


def maintenance_due(last_maintenance_at, now: float) -> bool:
    return last_maintenance_at is None or now - last_maintenance_at >= MAINTENANCE_MIN_GAP_SECONDS


def mood_set_point(social_need: float) -> float:
    loneliness = max(0.0, float(social_need) - LONELINESS_ONSET)
    return MOOD_SET_POINT - LONELINESS_MOOD_WEIGHT * loneliness


def relax_mood(mood: float, dt: float, *, asleep: bool, social_need: float = 0.0) -> float:
    tau = MOOD_RELAX_TAU_ASLEEP_SECONDS if asleep else MOOD_RELAX_TAU_AWAKE_SECONDS
    target = mood_set_point(social_need)
    return target + (mood - target) * math.exp(-max(0.0, dt) / tau)


def recover_fatigue(fatigue: float, dt: float) -> float:
    return fatigue * math.exp(-max(0.0, dt) / FATIGUE_RECOVERY_TAU_SECONDS)


def awake_seconds_between(start: float, end: float, sleep_intervals) -> float:
    """Seconds in [start, end] not covered by the given (onset, wake) intervals."""
    total = max(0.0, end - start)
    for onset, wake in sleep_intervals:
        overlap = min(end, wake) - max(start, onset)
        if overlap > 0:
            total -= overlap
    return max(0.0, total)
