"""
ReadMcpResourceTool – read a specific MCP resource.

Port of: src/tools/ReadMcpResourceTool/ReadMcpResourceTool.ts
"""
from __future__ import annotations
from typing import Any

TOOL_NAME = "ReadMcpResource"

def input_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "server": {"type": "string", "description": "MCP server name"},
            "uri": {"type": "string", "description": "Resource URI"},
        },
        "required": ["server", "uri"],
    }

async def call(server: str, uri: str, **kwargs: Any) -> dict[str, Any]:
    from hare.services.mcp_client import get_mcp_client
    client = get_mcp_client()
    result = await client.call_tool(server, "resources/read", {"uri": uri})
    return {"data": result}
