"""Port of: src/commands/mcp/. Manage MCP servers."""
from typing import Any
async def call(args: list[str], context: Any) -> dict[str, Any]:
    return {"type": "text", "value": "MCP servers (stub)."}
