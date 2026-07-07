"""Port of: src/commands/fast/"""
from __future__ import annotations
from typing import Any
COMMAND_NAME = "fast"
DESCRIPTION = "Toggle fast mode (use faster model)"
ALIASES: list[str] = []

async def call(args: str, messages: list[dict[str, Any]], **ctx: Any) -> dict[str, Any]:
    return {"type": "fast", "display_text": "Fast mode toggled."}
