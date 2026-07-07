"""
MCP SDK client orchestration (stdio/SSE/HTTP/WS).

Port of: src/services/mcp/client.ts — stub; TS module is large and ties to React/SDK.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class McpSessionHandle:
    server_name: str
    client: Any = None
    transport: Any = None


@dataclass
class McpClientPool:
    sessions: dict[str, McpSessionHandle] = field(default_factory=dict)

    async def connect_stdio(self, name: str, _command: list[str], **_kwargs: Any) -> McpSessionHandle:
        h = McpSessionHandle(server_name=name)
        self.sessions[name] = h
        return h

    async def connect_remote(self, name: str, _url: str, **_kwargs: Any) -> McpSessionHandle:
        h = McpSessionHandle(server_name=name)
        self.sessions[name] = h
        return h

    async def call_tool(
        self, server_name: str, tool_name: str, arguments: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        del server_name, tool_name, arguments
        return {"content": [], "is_error": False}

    async def disconnect(self, name: str) -> None:
        self.sessions.pop(name, None)


_default_pool: Optional[McpClientPool] = None


def get_mcp_client_pool() -> McpClientPool:
    global _default_pool
    if _default_pool is None:
        _default_pool = McpClientPool()
    return _default_pool
