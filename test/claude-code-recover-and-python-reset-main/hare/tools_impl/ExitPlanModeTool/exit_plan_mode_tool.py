"""
ExitPlanModeTool – exit plan mode, present plan for approval.

Port of: src/tools/ExitPlanModeTool/ExitPlanModeV2Tool.ts
"""
from __future__ import annotations
from typing import Any

TOOL_NAME = "ExitPlanMode"

def input_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "plan": {"type": "string", "description": "The plan content"},
        },
    }

async def call(plan: str = "", **kwargs: Any) -> dict[str, Any]:
    return {"data": "Exited plan mode.", "plan": plan}
