"""Port of: src/commands/hooks/. Manage hooks."""
from typing import Any
async def call(args: list[str], context: Any) -> dict[str, Any]:
    return {"type": "text", "value": "No hooks configured."}
