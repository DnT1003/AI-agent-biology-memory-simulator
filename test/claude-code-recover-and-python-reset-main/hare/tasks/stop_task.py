"""Port of: src/tasks/stopTask.ts"""
from __future__ import annotations
from typing import Any

async def stop_task(task_id: str) -> dict[str, Any]:
    return {"task_id": task_id, "status": "cancelled"}
