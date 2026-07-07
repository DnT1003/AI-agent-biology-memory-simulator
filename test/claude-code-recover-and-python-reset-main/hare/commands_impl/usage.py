"""Port of: src/commands/usage/. Show API usage."""
from typing import Any
async def call(args: list[str], context: Any) -> dict[str, Any]:
    return {"type": "text", "value": "Usage: 0 tokens (stub)."}
