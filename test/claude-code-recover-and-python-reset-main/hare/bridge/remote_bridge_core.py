"""Port of: src/bridge/remoteBridgeCore.ts"""
from __future__ import annotations
from typing import Any
from hare.bridge.repl_bridge import ReplBridgeHandle

async def init_env_less_bridge_core(config: Any) -> ReplBridgeHandle:
    return ReplBridgeHandle()
