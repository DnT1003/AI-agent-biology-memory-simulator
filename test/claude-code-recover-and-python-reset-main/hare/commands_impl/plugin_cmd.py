"""Port of: src/commands/plugin/"""
from __future__ import annotations
from typing import Any
COMMAND_NAME = "plugin"
DESCRIPTION = "Manage plugins"
ALIASES = ["plugins"]

async def call(args: str, messages: list[dict[str, Any]], **ctx: Any) -> dict[str, Any]:
    from hare.utils.plugins.plugin_loader import load_plugins
    plugins = load_plugins()
    if not plugins: return {"type": "plugin", "display_text": "No plugins installed."}
    lines = ["Installed plugins:"]
    for p in plugins: lines.append(f"  {p['name']} ({p['path']})")
    return {"type": "plugin", "display_text": "\n".join(lines)}
