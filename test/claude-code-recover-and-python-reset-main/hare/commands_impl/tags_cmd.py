"""Port of: src/commands/tags/"""
from __future__ import annotations
import asyncio
from typing import Any
COMMAND_NAME = "tag"
DESCRIPTION = "Manage git tags"
ALIASES = ["tags"]

async def call(args: str, messages: list[dict[str, Any]], **ctx: Any) -> dict[str, Any]:
    proc = await asyncio.create_subprocess_exec("git", "tag", "--list",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await proc.communicate()
    output = stdout.decode("utf-8", errors="replace")
    return {"type": "tag", "display_text": output.strip() or "No tags."}
