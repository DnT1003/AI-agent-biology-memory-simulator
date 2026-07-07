"""
EnterPlanModeTool – switch to plan mode.

Port of: src/tools/EnterPlanModeTool/EnterPlanModeTool.ts
"""
from __future__ import annotations
from typing import Any

TOOL_NAME = "EnterPlanMode"

def input_schema() -> dict[str, Any]:
    return {"type": "object", "properties": {}}

async def call(**kwargs: Any) -> dict[str, Any]:
    return {"data": "Entered plan mode. Tools are restricted to read-only operations."}
