"""Port of: src/bridge/pollConfig.ts + pollConfigDefaults.ts"""
from __future__ import annotations
from dataclasses import dataclass

@dataclass
class PollIntervalConfig:
    base_ms: int = 5000
    idle_ms: int = 15000
    busy_ms: int = 1000
    max_ms: int = 60000

DEFAULT_POLL_CONFIG = PollIntervalConfig()

def get_poll_interval_config() -> PollIntervalConfig:
    return DEFAULT_POLL_CONFIG
