"""Port of: src/bridge/initReplBridge.ts"""
from __future__ import annotations
from typing import Any
from hare.bridge.repl_bridge import ReplBridgeHandle, init_bridge_core
from hare.bridge.bridge_enabled import is_bridge_enabled

async def init_repl_bridge(options: dict[str, Any] | None = None) -> ReplBridgeHandle | None:
    if not is_bridge_enabled():
        return None
    return await init_bridge_core(options)
