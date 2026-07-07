"""
ExitWorktreeTool – leave a git worktree.

Port of: src/tools/ExitWorktreeTool/ExitWorktreeTool.ts
"""
from __future__ import annotations
import asyncio, os
from typing import Any

TOOL_NAME = "ExitWorktree"

def input_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["keep", "discard"], "description": "What to do with worktree"},
            "discard_changes": {"type": "boolean"},
        },
    }

async def call(action: str = "keep", discard_changes: bool = False, **kwargs: Any) -> dict[str, Any]:
    cwd = os.getcwd()
    if action == "discard":
        proc = await asyncio.create_subprocess_exec(
            "git", "worktree", "remove", cwd, "--force" if discard_changes else "",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
    return {"data": f"Exited worktree (action={action})"}
