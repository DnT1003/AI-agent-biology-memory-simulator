"""Reload active plugin components in-session. Port of refresh.ts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class RefreshActivePluginsResult:
    enabled_count: int = 0
    disabled_count: int = 0
    command_count: int = 0
    agent_count: int = 0
    hook_count: int = 0
    mcp_count: int = 0
    lsp_count: int = 0
    error_count: int = 0
    agent_definitions: Any = None
    plugin_commands: list[Any] = None


async def refresh_active_plugins(
    set_app_state: Callable[[Any], Any],
) -> RefreshActivePluginsResult:
    """Stub — clear caches and reload plugins/MCP/LSP."""
    _ = set_app_state
    return RefreshActivePluginsResult(plugin_commands=[])
