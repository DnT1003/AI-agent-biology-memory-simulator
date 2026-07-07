"""
MCPTool – stub tool; real name/args/call overridden by MCP client.

Port of: src/tools/MCPTool/MCPTool.ts
"""
from __future__ import annotations
from typing import Any

MCP_TOOL_NAME = "MCPTool"

def input_schema() -> dict[str, Any]:
    return {"type": "object", "properties": {}}

async def call(**kwargs: Any) -> dict[str, Any]:
    return {"data": ""}
