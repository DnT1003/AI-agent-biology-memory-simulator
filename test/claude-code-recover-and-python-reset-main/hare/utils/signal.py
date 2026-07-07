"""Port of: src/utils/signal.ts"""
from __future__ import annotations
from typing import Any, Callable

class Signal:
    def __init__(self) -> None:
        self._listeners: list[Callable[[], None]] = []
    def subscribe(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)
        def unsub():
            if listener in self._listeners: self._listeners.remove(listener)
        return unsub
    def emit(self) -> None:
        for l in self._listeners: l()

def create_signal() -> Signal:
    return Signal()
