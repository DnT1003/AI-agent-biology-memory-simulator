"""
Advisor command — inline suggestions / review.

Port of: src/commands/advisor.ts
"""

from __future__ import annotations

from typing import Any


async def run_advisor_command(_args: list[str]) -> dict[str, Any]:
    return {"ok": True}
