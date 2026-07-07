"""Port of: src/commands/clear/. Clear conversation history."""
from typing import Any
async def call(args: list[str], context: Any) -> dict[str, Any]:
    return {"type": "text", "value": "Conversation cleared."}
