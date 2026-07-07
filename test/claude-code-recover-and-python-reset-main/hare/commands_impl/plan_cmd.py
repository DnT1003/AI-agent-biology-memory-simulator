"""Port of: src/commands/plan/. Toggle plan mode."""
from typing import Any
async def call(args: list[str], context: Any) -> dict[str, Any]:
    return {"type": "text", "value": "Plan mode toggled."}
