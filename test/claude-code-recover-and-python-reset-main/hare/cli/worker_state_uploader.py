"""Worker state uploader (port of src/cli/transports/WorkerStateUploader.ts)."""

from __future__ import annotations

import asyncio
from typing import Any, Callable


class WorkerStateUploader:
    def __init__(
        self,
        *,
        send: Callable[[dict[str, Any]], Any],
        base_delay_ms: float,
        max_delay_ms: float,
        jitter_ms: float,
    ) -> None:
        self._send = send
        self._base = base_delay_ms
        self._max = max_delay_ms
        self._jitter = jitter_ms
        self._pending: dict[str, Any] | None = None
        self._closed = False

    def enqueue(self, patch: dict[str, Any]) -> None:
        if self._closed:
            return
        self._pending = {**(self._pending or {}), **patch}
        asyncio.get_event_loop().create_task(self._drain())

    async def _drain(self) -> None:
        if self._closed or not self._pending:
            return
        payload = self._pending
        self._pending = None
        await self._send(payload or {})

    def close(self) -> None:
        self._closed = True
        self._pending = None
