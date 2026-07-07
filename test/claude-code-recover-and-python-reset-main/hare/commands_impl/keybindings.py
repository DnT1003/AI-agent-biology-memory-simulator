"""Port of: src/commands/keybindings/"""
from __future__ import annotations
from typing import Any
COMMAND_NAME = "keybindings"
DESCRIPTION = "Show keyboard shortcuts"
ALIASES = ["keys"]

async def call(args: str, messages: list[dict[str, Any]], **ctx: Any) -> dict[str, Any]:
    lines = [
        "Keyboard shortcuts:",
        "  Ctrl+C  - Cancel current operation",
        "  Ctrl+D  - Exit session",
        "  Up/Down - Navigate history",
        "  Tab     - Autocomplete",
        "  Esc     - Clear input",
    ]
    return {"type": "keybindings", "display_text": "\n".join(lines)}
