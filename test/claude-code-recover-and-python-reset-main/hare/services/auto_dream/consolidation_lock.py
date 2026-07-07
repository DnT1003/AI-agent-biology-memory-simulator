"""
Cross-process lock for consolidation runs.

Port of: src/services/autoDream/consolidationLock.ts
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

_lock = asyncio.Lock()


@asynccontextmanager
async def consolidation_lock() -> AsyncIterator[None]:
    async with _lock:
        yield
