"""
Thinkback command — replay / inspect past reasoning.

Port of: src/commands/thinkback/index.ts
"""

from __future__ import annotations

from typing import Any


async def run_thinkback_command(_args: list[str]) -> dict[str, Any]:
    return {"ok": True}
