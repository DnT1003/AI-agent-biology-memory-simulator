"""Skill load analytics.

Port of: src/utils/telemetry/skillLoadedEvent.ts
"""

from __future__ import annotations

from typing import Any


async def log_skills_loaded(cwd: str, context_window_tokens: int) -> None:
    """Emit ``tengu_skill_loaded`` for each prompt skill (stub)."""
    del cwd, context_window_tokens
