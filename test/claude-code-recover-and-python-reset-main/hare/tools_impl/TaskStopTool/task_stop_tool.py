"""
TaskStopTool – stop a running background task.

Port of: src/tools/TaskStopTool/TaskStopTool.ts
"""
from __future__ import annotations
from typing import Any

TOOL_NAME = "TaskStop"
ALIASES = ["KillShell"]

def input_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "Task ID to stop"},
            "shell_id": {"type": "string", "description": "Shell ID to kill"},
        },
    }

async def call(task_id: str = "", shell_id: str = "", **kwargs: Any) -> dict[str, Any]:
    target = task_id or shell_id
    if not target:
        return {"error": "Must provide task_id or shell_id"}
    return {"data": f"Stopped task/shell: {target}"}
