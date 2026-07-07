"""Port of: src/commands/release-notes/"""
from __future__ import annotations
from typing import Any
COMMAND_NAME = "release-notes"
DESCRIPTION = "Show release notes"
ALIASES = ["changelog"]

async def call(args: str, messages: list[dict[str, Any]], **ctx: Any) -> dict[str, Any]:
    return {"type": "release-notes", "display_text": "Release notes not available in Python port."}
