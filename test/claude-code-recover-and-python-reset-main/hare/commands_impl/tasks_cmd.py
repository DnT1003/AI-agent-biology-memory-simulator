"""Port of: src/commands/tasks/"""
from __future__ import annotations
from typing import Any
COMMAND_NAME = "tasks"
DESCRIPTION = "List and manage background tasks"
ALIASES: list[str] = []

async def call(args: str, messages: list[dict[str, Any]], **ctx: Any) -> dict[str, Any]:
    return {"type": "tasks", "display_text": "No running tasks."}
