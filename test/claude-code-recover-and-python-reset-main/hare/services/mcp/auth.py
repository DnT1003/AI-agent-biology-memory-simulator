"""
MCP OAuth client (SDK + loopback); full implementation is environment-specific.

Port of: src/services/mcp/auth.ts (stub surface).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from hare.services.mcp.oauth_port import build_redirect_uri, find_available_port
from hare.services.mcp.types import McpHttpServerConfig, McpSseServerConfig


@dataclass
class McpOAuthTokens:
    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[float] = None


@dataclass
class McpOAuthClientMetadata:
    client_name: str = "claude-code"
    redirect_uris: list[str] = field(default_factory=list)


async def refresh_mcp_oauth_tokens_if_needed(
    _config: McpSseServerConfig | McpHttpServerConfig,
    tokens: McpOAuthTokens | None,
) -> McpOAuthTokens | None:
    return tokens


async def start_mcp_oauth_flow(
    _config: McpSseServerConfig | McpHttpServerConfig,
) -> McpOAuthTokens:
    port = await find_available_port()
    _ = build_redirect_uri(port)
    return McpOAuthTokens(access_token="")


def discover_oauth_metadata(_resource_url: str) -> dict[str, Any]:
    return {}
