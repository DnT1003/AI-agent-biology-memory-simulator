"""Port of: src/bridge/replBridgeHandle.ts"""
from __future__ import annotations
from hare.bridge.repl_bridge import ReplBridgeHandle

_handle: ReplBridgeHandle | None = None

def set_repl_bridge_handle(h: ReplBridgeHandle) -> None:
    global _handle
    _handle = h

def get_repl_bridge_handle() -> ReplBridgeHandle | None:
    return _handle

def get_self_bridge_compat_id() -> str:
    return _handle.state.bridge_id if _handle else ""
