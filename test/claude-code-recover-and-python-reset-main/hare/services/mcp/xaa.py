"""
Cross-app access token exchange for MCP OAuth (stub).

Port of: src/services/mcp/xaa.ts
"""

from __future__ import annotations


class XaaTokenExchangeError(Exception):
    pass


async def perform_cross_app_access(_refresh_token: str, _audience: str) -> dict[str, str]:
    raise XaaTokenExchangeError("XAA token exchange not implemented in Python stub")
