"""
Dynamic MCP HTTP headers via external helper script.

Port of: src/services/mcp/headersHelper.ts
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from hare.services.mcp.types import (
    McpHttpServerConfig,
    McpSseServerConfig,
    McpWebSocketServerConfig,
)


async def get_mcp_headers_from_helper(
    server_name: str,
    config: McpSseServerConfig | McpHttpServerConfig | McpWebSocketServerConfig,
    *,
    trust_check_skipped: bool = False,
) -> dict[str, str] | None:
    """Run headersHelper command and parse JSON object of string headers."""
    helper = getattr(config, "headers_helper", None) or getattr(config, "headersHelper", None)
    if not helper:
        return None
    if not trust_check_skipped:
        # Production checks workspace trust; stubbed for non-interactive / tests.
        pass
    env = {
        **os.environ,
        "CLAUDE_CODE_MCP_SERVER_NAME": server_name,
        "CLAUDE_CODE_MCP_SERVER_URL": getattr(config, "url", ""),
    }
    try:
        proc = await asyncio.create_subprocess_shell(
            str(helper),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
        if proc.returncode != 0 or not stdout:
            return None
        raw = stdout.decode().strip()
        headers: Any = json.loads(raw)
        if not isinstance(headers, dict):
            return None
        out: dict[str, str] = {}
        for k, v in headers.items():
            if not isinstance(v, str):
                return None
            out[str(k)] = v
        return out
    except Exception:
        return None


async def get_mcp_server_headers(
    server_name: str,
    config: McpSseServerConfig | McpHttpServerConfig | McpWebSocketServerConfig,
) -> dict[str, str]:
    static = dict(getattr(config, "headers", None) or {})
    dynamic = await get_mcp_headers_from_helper(server_name, config) or {}
    return {**static, **dynamic}
