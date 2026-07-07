"""Port of: src/utils/hooks/sessionHooks.ts"""
from __future__ import annotations
from typing import Any

_session_hooks: list[dict[str, Any]] = []

def register_session_hook(hook: dict[str, Any]) -> None:
    _session_hooks.append(hook)

def clear_session_hooks() -> None:
    _session_hooks.clear()

def get_session_hooks() -> list[dict[str, Any]]:
    return list(_session_hooks)
