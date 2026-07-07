"""Port of: src/commands/help/. Show help."""
from typing import Any
async def call(args: list[str], context: Any) -> dict[str, Any]:
    return {"type": "text", "value": "Available commands: /help, /model, /config, /clear, /compact, /cost, /diff, /status, /exit, etc."}
