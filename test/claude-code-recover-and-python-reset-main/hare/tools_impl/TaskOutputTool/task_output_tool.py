"""Port of: src/tools/TaskOutputTool/TaskOutputTool.tsx"""
from __future__ import annotations
from typing import Any

TASK_OUTPUT_TOOL_NAME = "TaskOutput"

def input_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "task_id": {"type": "string"},
        },
        "required": ["task_id"],
    }

async def call(tool_input: dict[str, Any], **ctx: Any) -> dict[str, Any]:
    task_id = tool_input.get("task_id", "")
    from hare.utils.task.disk_output import load_task_output
    result = load_task_output(task_id)
    if result is None:
        return {"type": "error", "error": f"No output for task {task_id}"}
    return {"type": "tool_result", "content": str(result), "is_error": False}
