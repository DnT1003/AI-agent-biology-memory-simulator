"""Port of: src/commands/bridge/. Remote control bridge."""
from typing import Any
async def call(args: list[str], context: Any) -> dict[str, Any]:
    return {"type": "text", "value": "Remote control bridge (stub)."}
