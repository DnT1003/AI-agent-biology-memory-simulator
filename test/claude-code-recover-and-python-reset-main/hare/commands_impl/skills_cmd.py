"""Port of: src/commands/skills/. List available skills."""
from typing import Any
async def call(args: list[str], context: Any) -> dict[str, Any]:
    return {"type": "text", "value": "Available skills (stub)."}
