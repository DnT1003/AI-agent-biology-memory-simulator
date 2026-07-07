"""
Filesystem watcher for team memory files.

Port of: src/services/teamMemorySync/watcher.ts
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Callable


async def watch_team_memory_paths(
    roots: list[Path],
    on_change: Callable[[Path], None],
) -> asyncio.Task[None]:
    """Stub watcher — polls periodically."""

    async def _loop() -> None:
        while True:
            await asyncio.sleep(2.0)
            for r in roots:
                if r.exists():
                    on_change(r)

    return asyncio.create_task(_loop())
