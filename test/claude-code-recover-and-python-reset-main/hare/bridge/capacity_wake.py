"""
Capacity wake – signals for session capacity management.

Port of: src/bridge/capacityWake.ts
"""
from __future__ import annotations
import asyncio


class CapacityWake:
    def __init__(self) -> None:
        self._event = asyncio.Event()

    def signal(self) -> None:
        self._event.set()

    async def wait(self, timeout: float | None = None) -> bool:
        try:
            if timeout:
                await asyncio.wait_for(self._event.wait(), timeout)
            else:
                await self._event.wait()
            self._event.clear()
            return True
        except asyncio.TimeoutError:
            return False

    def reset(self) -> None:
        self._event.clear()


def create_capacity_wake() -> CapacityWake:
    return CapacityWake()
