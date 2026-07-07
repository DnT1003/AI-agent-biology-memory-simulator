"""
Plugin cache invalidation and orphaned version GC.

Port of: src/utils/plugins/cacheUtils.ts
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from hare.utils.debug import log_for_debugging

ORPHANED_AT_FILENAME = ".orphaned_at"
CLEANUP_AGE_MS = 7 * 24 * 60 * 60 * 1000


def clear_all_plugin_caches() -> None:
    """Invalidate in-memory plugin caches — stub hooks to loader modules."""
    pass


def clear_all_caches() -> None:
    """Clear plugin caches plus commands/agents/skills caches."""
    clear_all_plugin_caches()


async def mark_plugin_version_orphaned(version_path: str) -> None:
    import asyncio

    p = Path(version_path) / ORPHANED_AT_FILENAME
    try:
        await asyncio.to_thread(
            p.write_text, str(int(time.time() * 1000)), encoding="utf-8"
        )
    except OSError as e:
        log_for_debugging(f"Failed to write .orphaned_at: {version_path}: {e}")


async def cleanup_orphaned_plugin_versions_in_background() -> None:
    """Remove stale orphaned plugin dirs after grace period — simplified stub."""
    try:
        from hare.utils.plugins.zip_cache import is_plugin_zip_cache_enabled

        if is_plugin_zip_cache_enabled():
            return
    except ImportError:
        pass
    log_for_debugging("cleanup_orphaned_plugin_versions_in_background (stub)")


def _get_orphaned_at_path(version_path: str) -> str:
    return str(Path(version_path) / ORPHANED_AT_FILENAME)
