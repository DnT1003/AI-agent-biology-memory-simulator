"""
MCP tool/server name parsing and display helpers.

Port of: src/services/mcp/mcpStringUtils.ts
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from hare.services.mcp.normalization import normalize_name_for_mcp


@dataclass
class McpInfo:
    server_name: str
    tool_name: Optional[str] = None


def mcp_info_from_string(tool_string: str) -> McpInfo | None:
    parts = tool_string.split("__")
    if len(parts) < 2:
        return None
    mcp_part = parts[0]
    server_name = parts[1]
    tool_name_parts = parts[2:]
    if mcp_part != "mcp" or not server_name:
        return None
    tool_name = "__".join(tool_name_parts) if tool_name_parts else None
    return McpInfo(server_name=server_name, tool_name=tool_name)


def get_mcp_prefix(server_name: str) -> str:
    return f"mcp__{normalize_name_for_mcp(server_name)}__"


def build_mcp_tool_name(server_name: str, tool_name: str) -> str:
    return f"{get_mcp_prefix(server_name)}{normalize_name_for_mcp(tool_name)}"


def get_tool_name_for_permission_check(tool: object) -> str:
    name = getattr(tool, "name", "")
    mcp_info = getattr(tool, "mcp_info", None)
    if mcp_info is not None:
        sn = getattr(mcp_info, "server_name", None) or mcp_info.get("serverName")  # type: ignore[union-attr]
        tn = getattr(mcp_info, "tool_name", None) or mcp_info.get("toolName")  # type: ignore[union-attr]
        if sn and tn:
            return build_mcp_tool_name(str(sn), str(tn))
    return str(name)


def get_mcp_display_name(full_name: str, server_name: str) -> str:
    prefix = f"mcp__{normalize_name_for_mcp(server_name)}__"
    return full_name.replace(prefix, "", 1)


def extract_mcp_tool_display_name(user_facing_name: str) -> str:
    without_suffix = user_facing_name.replace("(MCP)", "").strip()
    dash = " - "
    idx = without_suffix.find(dash)
    if idx != -1:
        return without_suffix[idx + len(dash) :].strip()
    return without_suffix
