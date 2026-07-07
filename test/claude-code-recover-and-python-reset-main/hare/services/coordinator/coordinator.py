"""
Coordinator – orchestrates query, tool use, and conversation flow.

Port of: src/services/coordinator/coordinator.ts
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator


@dataclass
class Coordinator:
    context: Any = None
    _running: bool = False

    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def process_message(self, message: str) -> AsyncIterator[dict[str, Any]]:
        """Process a user message and yield response events. Stub."""
        yield {"type": "text", "content": ""}

    @property
    def is_running(self) -> bool:
        return self._running


_instance: Coordinator | None = None


def get_coordinator() -> Coordinator:
    global _instance
    if _instance is None:
        _instance = Coordinator()
    return _instance
