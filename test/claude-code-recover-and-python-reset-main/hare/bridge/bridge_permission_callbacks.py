"""Port of: src/bridge/bridgePermissionCallbacks.ts"""
from __future__ import annotations
from typing import Any
from hare.bridge.types import PermissionResponseEvent

def is_bridge_permission_response(event: dict[str, Any]) -> bool:
    return event.get("type") == "permission_response"
