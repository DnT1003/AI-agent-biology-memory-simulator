"""Auto-dream configuration. Port of: src/services/autoDream/config.ts"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AutoDreamConfig:
    enabled: bool = False
    min_idle_minutes: int = 30
