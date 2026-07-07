"""Port of: src/commands/status/. Show session status."""
from typing import Any
async def call(args: list[str], context: Any) -> dict[str, Any]:
    return {"type": "text", "value": "Status: active (stub)."}
