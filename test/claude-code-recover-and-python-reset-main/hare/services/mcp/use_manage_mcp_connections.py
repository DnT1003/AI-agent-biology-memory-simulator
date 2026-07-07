"""
Session-scoped MCP connection lifecycle (non-React equivalent of the TS hook).

Port of: src/services/mcp/useManageMCPConnections.ts
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from hare.services.mcp.channel_allowlist import is_channels_enabled
from hare.services.mcp.channel_permissions import is_channel_permission_relay_enabled


@dataclass
class ManageMcpConnectionsState:
    servers: list[dict[str, Any]] = field(default_factory=list)
    permission_relay: bool = False
    channels_enabled: bool = False


class ManageMcpConnections:
    """Owns subscribe/refresh for MCP connections (stub)."""

    def __init__(self) -> None:
        self._state = ManageMcpConnectionsState()
        self._state.channels_enabled = is_channels_enabled()
        self._state.permission_relay = is_channel_permission_relay_enabled()

    def get_state(self) -> ManageMcpConnectionsState:
        return self._state

    async def refresh(self) -> None:
        return

    def subscribe(self, _cb: Callable[[ManageMcpConnectionsState], None]) -> Callable[[], None]:
        return lambda: None
