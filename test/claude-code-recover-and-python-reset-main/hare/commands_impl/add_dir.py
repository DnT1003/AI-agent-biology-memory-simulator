"""Port of: src/commands/add-dir/"""
from __future__ import annotations
from typing import Any
COMMAND_NAME = "add-dir"
DESCRIPTION = "Add a directory to the context"
ALIASES: list[str] = []

async def call(args: str, messages: list[dict[str, Any]], **ctx: Any) -> dict[str, Any]:
    path = args.strip()
    if not path: return {"type": "error", "display_text": "Usage: /add-dir <path>"}
    import os
    if not os.path.isdir(path): return {"type": "error", "display_text": f"Not a directory: {path}"}
    return {"type": "add-dir", "path": path, "display_text": f"Added directory: {path}"}
