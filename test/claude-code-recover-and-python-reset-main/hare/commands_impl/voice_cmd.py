"""Port of: src/commands/voice/. Voice input."""
from typing import Any
async def call(args: list[str], context: Any) -> dict[str, Any]:
    return {"type": "text", "value": "Voice input (stub)."}
