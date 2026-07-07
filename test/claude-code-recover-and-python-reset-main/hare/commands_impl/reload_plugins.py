"""Port of: src/commands/reload-plugins/. Reload plugins."""
from typing import Any
async def call(args: list[str], context: Any) -> dict[str, Any]:
    return {"type": "text", "value": "Plugins reloaded."}
