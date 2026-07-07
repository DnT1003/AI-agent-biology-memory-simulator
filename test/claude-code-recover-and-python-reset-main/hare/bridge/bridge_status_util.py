"""Port of: src/bridge/bridgeStatusUtil.ts"""
from __future__ import annotations

def get_bridge_status(connected: bool, session_count: int = 0) -> str:
    if not connected:
        return "Bridge: disconnected"
    return f"Bridge: connected ({session_count} sessions)"
