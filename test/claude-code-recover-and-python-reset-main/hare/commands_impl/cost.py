"""Port of: src/commands/cost/. Show cost estimate."""
from typing import Any
async def call(args: list[str], context: Any) -> dict[str, Any]:
    return {"type": "text", "value": "Cost estimate: $0.00 (stub)"}
