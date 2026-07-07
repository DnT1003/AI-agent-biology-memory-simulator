"""
Skill improvement loop (post-sampling).

Port of: src/utils/hooks/skillImprovement.ts
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class SkillUpdate:
    section: str
    change: str
    reason: str


async def maybe_run_skill_improvement(_messages: list[Any], _context: dict[str, Any]) -> list[SkillUpdate]:
    """Stub: returns no updates until API wiring exists."""
    return []
