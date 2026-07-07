"""
GrowthBook config for time-based microcompact.

Port of: src/services/compact/timeBasedMCConfig.ts
"""

from __future__ import annotations

from dataclasses import dataclass

from hare.services.analytics.growthbook import get_feature_value_cached_may_be_stale


@dataclass
class TimeBasedMCConfig:
    enabled: bool = False
    gap_threshold_minutes: int = 60
    keep_recent: int = 5


_DEFAULTS = TimeBasedMCConfig()


def get_time_based_mc_config() -> TimeBasedMCConfig:
    raw = get_feature_value_cached_may_be_stale("tengu_slate_heron", None)
    if isinstance(raw, dict):
        return TimeBasedMCConfig(
            enabled=bool(raw.get("enabled", _DEFAULTS.enabled)),
            gap_threshold_minutes=int(raw.get("gapThresholdMinutes", _DEFAULTS.gap_threshold_minutes)),
            keep_recent=int(raw.get("keepRecent", _DEFAULTS.keep_recent)),
        )
    return _DEFAULTS
