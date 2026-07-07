"""Port of: src/utils/settings/changeDetector.ts"""
from __future__ import annotations
from typing import Any, Callable

_listeners: list[Callable[[], None]] = []

def settings_change_detector() -> None:
    for listener in _listeners:
        listener()

def on_settings_change(listener: Callable[[], None]) -> Callable[[], None]:
    _listeners.append(listener)
    def unsub():
        _listeners.remove(listener)
    return unsub
