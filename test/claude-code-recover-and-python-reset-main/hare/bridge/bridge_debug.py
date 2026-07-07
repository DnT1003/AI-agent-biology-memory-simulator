"""Port of: src/bridge/bridgeDebug.ts"""
from __future__ import annotations
from typing import Any

_fault_registry: dict[str, Any] = {}

def inject_bridge_fault(name: str, fault: Any) -> None:
    _fault_registry[name] = fault

def get_bridge_fault(name: str) -> Any:
    return _fault_registry.get(name)
