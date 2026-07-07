"""
Inbound notifications from MCP channel servers (`notifications/claude/channel`).

Port of: src/services/mcp/channelNotification.ts (schemas and constants; handlers stubbed).
"""

from __future__ import annotations

from typing import Any

CHANNEL_PERMISSION_METHOD = "notifications/claude/channel/permission"
CHANNEL_TAG = "channel"


def channel_message_notification_schema() -> dict[str, Any]:
    return {
        "method": "notifications/claude/channel",
        "params": {"content": str, "meta": dict[str, str]},
    }


def channel_permission_notification_schema() -> dict[str, Any]:
    return {
        "method": CHANNEL_PERMISSION_METHOD,
        "params": {"request_id": str, "behavior": ("allow", "deny")},
    }


async def handle_channel_notification(_server_name: str, _payload: dict[str, Any]) -> None:
    """Enqueue channel content for the model (stub)."""
    return
