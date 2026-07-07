"""
FlushGate – queue messages during history flush.

Port of: src/bridge/flushGate.ts
"""
from __future__ import annotations
import asyncio
from typing import Any, Generic, TypeVar

T = TypeVar("T")


class FlushGate:
    def __init__(self) -> None:
        self._flushing = False
        self._queue: list[Any] = []
        self._event = asyncio.Event()
        self._event.set()

    def start_flush(self) -> None:
        self._flushing = True
        self._event.clear()

    def end_flush(self) -> list[Any]:
        self._flushing = False
        self._event.set()
        queued = list(self._queue)
        self._queue.clear()
        return queued

    async def wait_if_flushing(self) -> None:
        await self._event.wait()

    def enqueue(self, item: Any) -> None:
        if self._flushing:
            self._queue.append(item)

    @property
    def is_flushing(self) -> bool:
        return self._flushing
