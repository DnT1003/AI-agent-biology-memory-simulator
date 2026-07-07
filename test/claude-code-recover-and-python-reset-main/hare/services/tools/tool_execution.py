"""
Tool execution orchestration.

Port of: src/services/tools/toolExecution.ts
"""

from __future__ import annotations

import time
from typing import Any, AsyncGenerator


McpServerType = str | None


async def check_permissions_and_call_tool(
    tool: Any,
    tool_use_id: str,
    raw_input: dict[str, Any],
    tool_use_context: Any,
    can_use_tool: Any = None,
    assistant_message: Any = None,
    message_id: str = "",
    request_id: str | None = None,
    mcp_server_type: McpServerType = None,
    mcp_server_base_url: str | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """
    Run the full tool execution pipeline:
    1. Pre-tool hooks
    2. Permission check
    3. Tool call
    4. Post-tool hooks

    Yields events as they occur.
    """
    start_time = time.time()

    try:
        result = await tool.call(
            raw_input,
            tool_use_context,
            can_use_tool,
            assistant_message,
        )
        yield {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "result": result,
            "duration_ms": int((time.time() - start_time) * 1000),
        }
    except Exception as exc:
        yield {
            "type": "tool_error",
            "tool_use_id": tool_use_id,
            "error": str(exc),
            "duration_ms": int((time.time() - start_time) * 1000),
        }
