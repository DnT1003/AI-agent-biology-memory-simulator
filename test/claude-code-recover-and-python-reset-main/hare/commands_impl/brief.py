"""
Brief command — condensed session output.

Port of: src/commands/brief.ts
"""

from __future__ import annotations

from typing import Any


async def run_brief_command(_args: list[str]) -> dict[str, Any]:
    return {"ok": True, "brief": ""}
