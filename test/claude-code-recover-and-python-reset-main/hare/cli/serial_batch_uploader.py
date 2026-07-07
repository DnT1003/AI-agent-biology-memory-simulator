"""Serial batch event uploader (port of src/cli/transports/SerialBatchEventUploader.ts)."""

from __future__ import annotations

import asyncio
import json
import random
from typing import Any, Callable, Generic, TypeVar

T = TypeVar("T")


class RetryableError(Exception):
    def __init__(self, message: str, retry_after_ms: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_ms = retry_after_ms


class SerialBatchEventUploader(Generic[T]):
    def __init__(
        self,
        *,
        max_batch_size: int,
        max_queue_size: int,
        send: Callable[[list[T]], Any],
        base_delay_ms: float,
        max_delay_ms: float,
        jitter_ms: float,
        max_batch_bytes: int | None = None,
        max_consecutive_failures: int | None = None,
        on_batch_dropped: Any | None = None,
    ) -> None:
        self._max_batch_size = max_batch_size
        self._max_queue_size = max_queue_size
        self._send = send
        self._base = base_delay_ms
        self._max = max_delay_ms
        self._jitter = jitter_ms
        self._pending: list[T] = []
        self._closed = False
        self._dropped = 0

    @property
    def dropped_batch_count(self) -> int:
        return self._dropped

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    async def enqueue(self, events: T | list[T]) -> None:
        items = events if isinstance(events, list) else [events]
        self._pending.extend(items)

    async def flush(self) -> None:
        if not self._pending:
            return
        batch = self._pending[: self._max_batch_size]
        self._pending = self._pending[len(batch) :]
        await self._send(batch)

    def close(self) -> None:
        self._closed = True
        self._pending.clear()
