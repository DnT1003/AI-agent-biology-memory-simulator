"""Port of: src/commands/remote-env/. Remote environment."""
from typing import Any
async def call(args: list[str], context: Any) -> dict[str, Any]:
    return {"type": "text", "value": "Remote environment (stub)."}
