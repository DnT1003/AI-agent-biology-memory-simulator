"""Port of: src/tools/McpAuthTool/McpAuthTool.ts"""
from __future__ import annotations
from typing import Any

def input_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "server_name": {"type": "string"},
            "action": {"type": "string", "enum": ["authorize", "revoke"]},
        },
        "required": ["server_name"],
    }

async def call(tool_input: dict[str, Any], **ctx: Any) -> dict[str, Any]:
    server = tool_input.get("server_name", "")
    action = tool_input.get("action", "authorize")
    return {"type": "tool_result", "content": f"MCP auth {action} for {server} (stub)", "is_error": False}
