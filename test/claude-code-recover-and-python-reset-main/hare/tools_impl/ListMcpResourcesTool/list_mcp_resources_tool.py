"""
ListMcpResourcesTool – list MCP server resources.

Port of: src/tools/ListMcpResourcesTool/ListMcpResourcesTool.ts
"""
from __future__ import annotations
from typing import Any

TOOL_NAME = "ListMcpResources"

def input_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "server": {"type": "string", "description": "Optional server name filter"},
        },
    }

async def call(server: str | None = None, **kwargs: Any) -> dict[str, Any]:
    from hare.services.mcp_client import get_mcp_client
    client = get_mcp_client()
    tools = await client.list_tools()
    if server:
        tools = [t for t in tools if t.get("server") == server]
    return {"resources": tools}
