"""Port of: src/utils/hooks/hooksConfigManager.ts"""
from __future__ import annotations
from typing import Any

_hooks_config: dict[str, list[dict[str, Any]]] = {}

def register_hooks(event: str, hooks: list[dict[str, Any]]) -> None:
    _hooks_config.setdefault(event, []).extend(hooks)

def get_hooks_for_event(event: str) -> list[dict[str, Any]]:
    return _hooks_config.get(event, [])

def clear_hooks() -> None:
    _hooks_config.clear()
