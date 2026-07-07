"""Port of: src/commands/chrome/. Chrome integration."""
from typing import Any
async def call(args: list[str], context: Any) -> dict[str, Any]:
    return {"type": "text", "value": "Chrome integration (stub)."}
