"""Port of: src/commands/privacy-settings/"""
from __future__ import annotations
from typing import Any
COMMAND_NAME = "privacy"
DESCRIPTION = "View or change privacy settings"
ALIASES = ["privacy-settings"]

async def call(args: str, messages: list[dict[str, Any]], **ctx: Any) -> dict[str, Any]:
    return {"type": "privacy", "display_text": "Privacy settings: analytics enabled, telemetry enabled."}
