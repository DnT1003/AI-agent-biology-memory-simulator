"""Port of: src/commands/resume/. Resume a previous session."""
from typing import Any
async def call(args: list[str], context: Any) -> dict[str, Any]:
    return {"type": "text", "value": "Session resume (stub)."}
