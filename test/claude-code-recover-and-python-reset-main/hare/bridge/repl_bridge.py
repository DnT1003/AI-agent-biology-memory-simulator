"""Port of: src/bridge/replBridge.ts"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

@dataclass
class BridgeState:
    connected: bool = False
    session_id: str = ""
    bridge_id: str = ""

@dataclass
class ReplBridgeHandle:
    state: BridgeState = field(default_factory=BridgeState)
    async def send_message(self, msg: str) -> None: pass
    async def disconnect(self) -> None: self.state.connected = False
    @property
    def is_connected(self) -> bool: return self.state.connected

async def init_bridge_core(config: Any) -> ReplBridgeHandle:
    return ReplBridgeHandle()
