"""Port of: src/commands/btw/. Side question / follow-up command."""
from typing import Any
async def call(args: list[str], context: Any) -> dict[str, Any]:
    return {"type": "text", "value": "BTW command: send a side question to Claude."}
