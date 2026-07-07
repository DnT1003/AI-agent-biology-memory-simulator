"""Port of: src/commands/heapdump/. Debug heap dump."""
from typing import Any
async def call(args: list[str], context: Any) -> dict[str, Any]:
    return {"type": "text", "value": "Heapdump not available in Python runtime."}
