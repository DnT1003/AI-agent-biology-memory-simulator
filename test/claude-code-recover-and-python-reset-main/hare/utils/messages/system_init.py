"""Build `system/init` SDK message. Port of: src/utils/messages/systemInit.ts"""

from __future__ import annotations

from typing import Any

from hare.utils.cwd import get_cwd


def sdk_compat_tool_name(name: str) -> str:
    """Map Agent tool wire name for legacy SDK consumers."""
    if name == "Agent":
        return "Task"
    return name


def build_system_init_message(inputs: dict[str, Any]) -> dict[str, Any]:
    """Assemble system/init payload (stub — merge with bootstrap state in real use)."""
    tools = [sdk_compat_tool_name(t["name"]) for t in inputs.get("tools", [])]
    return {
        "type": "system",
        "subtype": "init",
        "cwd": get_cwd(),
        "tools": tools,
        "mcp_servers": [{"name": c["name"], "status": c["type"]} for c in inputs.get("mcpClients", [])],
        "model": inputs.get("model", ""),
        "permissionMode": inputs.get("permissionMode", "default"),
    }
