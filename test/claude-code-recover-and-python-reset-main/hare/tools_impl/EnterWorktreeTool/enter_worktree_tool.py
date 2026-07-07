"""
EnterWorktreeTool – create and switch to a git worktree.

Port of: src/tools/EnterWorktreeTool/EnterWorktreeTool.ts
"""
from __future__ import annotations
import asyncio, os
from typing import Any

TOOL_NAME = "EnterWorktree"

def input_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Optional worktree branch name"},
        },
    }

async def call(name: str | None = None, **kwargs: Any) -> dict[str, Any]:
    cwd = os.getcwd()
    branch = name or "claude-worktree"
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "worktree", "add", "-b", branch, f"../{branch}",
            cwd=cwd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            return {"error": stderr.decode(errors="replace")}
        worktree_path = os.path.normpath(os.path.join(cwd, "..", branch))
        return {"data": f"Created worktree at {worktree_path}", "path": worktree_path}
    except Exception as e:
        return {"error": str(e)}
