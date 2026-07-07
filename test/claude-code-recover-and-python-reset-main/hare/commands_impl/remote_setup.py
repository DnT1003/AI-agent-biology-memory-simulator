"""Port of: src/commands/remote-setup/. Remote session setup."""
from typing import Any
async def call(args: list[str], context: Any) -> dict[str, Any]:
    return {"type": "text", "value": "Remote setup (stub)."}
