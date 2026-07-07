"""Port of: src/commands/exit/"""
from __future__ import annotations
from typing import Any
COMMAND_NAME = "exit"
DESCRIPTION = "Exit the session"
ALIASES = ["quit", "q"]

async def call(args: str, messages: list[dict[str, Any]], **ctx: Any) -> dict[str, Any]:
    return {"type": "exit", "display_text": "Goodbye!"}
