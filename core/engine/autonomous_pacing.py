"""Time-based pacing for autonomous behaviour.

The background loop polls about once per second. Every decision here is a
hazard over the real elapsed time ``dt`` (``p = 1 - exp(-dt / mean)``) plus a
minimum gap, so behaviour frequency depends on wall time and not on how often
the loop happens to iterate. Clocks and randomness are injected by the caller,
which keeps whole-day simulations deterministic in tests.
"""

import math
import random
from typing import Callable

from config import Config


def _minutes(value: float) -> float:
    return float(value) * 60.0


def _hours(value: float) -> float:
    return float(value) * 3600.0


class AutonomousPacer:
    """Decides when Aura may mind-wander, message the user, read or worry."""

    # Effects that belong to the pacing contract rather than to tuning knobs.
    RUMINATION_STRESS_STEP = 0.02
    PING_SOCIAL_RELIEF = 0.15
    READING_CURIOSITY_RELIEF = 0.15

    def __init__(self, rng: Callable[[], float] | None = None, config=Config):
        self._rng = rng or random.random
        self.mind_wander_mean = _minutes(config.MIND_WANDER_MEAN_MINUTES)
        self.mind_wander_min_gap = _minutes(config.MIND_WANDER_MIN_GAP_MINUTES)
        self.ping_mean_at_threshold = _hours(config.PING_MEAN_HOURS)
        self.ping_min_gap = _minutes(config.PING_MIN_GAP_MINUTES)
        self.ping_max_unanswered = int(config.PING_MAX_UNANSWERED)
        self.ping_backoff_cap = _hours(config.PING_BACKOFF_CAP_HOURS)
        self.reading_mean_at_threshold = _hours(config.READING_MEAN_HOURS)
        self.reading_min_gap = _minutes(config.READING_MIN_GAP_MINUTES)
        self.anxiety_threshold = float(config.ANXIETY_THRESHOLD)
        self.quiet_start, self.quiet_end = config.QUIET_HOURS

        self.last_mind_wander_at: float | None = None
        self.last_ping_at: float | None = None
        self.unanswered_pings = 0
        self._ping_interaction_marker: float | None = None
        self.last_reading_at: float | None = None
        self._anxiety_episode: float | None = None
        self._anxiety_stage = 0

    # ------------------------------------------------------------------ utils
    def _hazard(self, dt: float, mean_interval: float) -> bool:
        if dt <= 0.0 or mean_interval <= 0.0:
            return False
        return self._rng() < 1.0 - math.exp(-dt / mean_interval)

    @staticmethod
    def _gap_elapsed(now: float, last: float | None, gap: float) -> bool:
        return last is None or now - last >= gap

    def is_quiet_hour(self, hour: int) -> bool:
        start, end = self.quiet_start, self.quiet_end
        if start == end:
            return False
        if start < end:
            return start <= hour < end
        return hour >= start or hour < end

    # ------------------------------------------------------------ mind wander
    def should_mind_wander(self, now: float, dt: float, stress: float, mood: float) -> bool:
        """Spontaneous memory recall; stress and low mood make it more frequent."""
        if not self._gap_elapsed(now, self.last_mind_wander_at, self.mind_wander_min_gap):
            return False
        intensity = 1.0 + 2.0 * max(0.0, stress) + max(0.0, -mood)
        if not self._hazard(dt, self.mind_wander_mean / intensity):
            return False
        self.last_mind_wander_at = now
        return True

    # ------------------------------------------------------------------- ping
    def observe_interaction(self, last_interaction_time: float) -> None:
        """A user message after our last ping resets the unanswered back-off."""
        marker = self._ping_interaction_marker
        if marker is not None and last_interaction_time > marker:
            self.unanswered_pings = 0
            self._ping_interaction_marker = None

    def ping_allowed(self, now: float, hour: int) -> bool:
        if self.is_quiet_hour(hour):
            return False
        if self.unanswered_pings >= self.ping_max_unanswered:
            return False
        gap = min(
            self.ping_backoff_cap,
            self.ping_min_gap * (2 ** self.unanswered_pings),
        )
        return self._gap_elapsed(now, self.last_ping_at, gap)

    def should_ping(
        self, now: float, dt: float, social_need: float, hour: int,
        motivation: float = 1.0,
    ) -> bool:
        """``motivation`` (dopamine, 0.5..1.5) scales how readily Aura reaches out."""
        if social_need <= 0.6 or not self.ping_allowed(now, hour):
            return False
        urgency = 1.0 + 3.0 * (min(1.0, social_need) - 0.6) / 0.4
        return self._hazard(dt, self.ping_mean_at_threshold / (urgency * motivation))

    def record_ping(self, now: float, last_interaction_time: float, *, sent: bool = True) -> None:
        """Start the gap after every attempt; only a delivered message awaits a reply."""
        self.observe_interaction(last_interaction_time)
        self.last_ping_at = now
        if sent:
            self.unanswered_pings += 1
            self._ping_interaction_marker = last_interaction_time

    # ---------------------------------------------------------------- reading
    def should_read(
        self, now: float, dt: float, curiosity: float, motivation: float = 1.0
    ) -> bool:
        if curiosity <= 0.7:
            return False
        if not self._gap_elapsed(now, self.last_reading_at, self.reading_min_gap):
            return False
        eagerness = 1.0 + 3.0 * (min(1.0, curiosity) - 0.7) / 0.3
        return self._hazard(dt, self.reading_mean_at_threshold / (eagerness * motivation))

    def record_reading(self, now: float) -> None:
        self.last_reading_at = now

    # ---------------------------------------------------------------- anxiety
    def anxiety_stage_due(self, idle_seconds: float, last_interaction_time: float, hour: int) -> int:
        """Return 1 or 2 once per absence episode when a threshold is crossed."""
        if self._anxiety_episode != last_interaction_time:
            self._anxiety_episode = last_interaction_time
            self._anxiety_stage = 0
        if self.is_quiet_hour(hour) or self.anxiety_threshold <= 0.0:
            return 0
        if self._anxiety_stage < 1 and idle_seconds >= self.anxiety_threshold:
            self._anxiety_stage = 1
            return 1
        if self._anxiety_stage < 2 and idle_seconds >= 4.0 * self.anxiety_threshold:
            self._anxiety_stage = 2
            return 2
        return 0
