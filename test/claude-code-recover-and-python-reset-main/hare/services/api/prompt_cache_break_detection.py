"""
Detects prompt-cache invalidation reasons (system/tools/model changes).

Port of: src/services/api/promptCacheBreakDetection.ts — stub hooks only.
"""

from __future__ import annotations

from typing import Any


async def notify_compaction(_reason: str, _meta: dict[str, Any] | None = None) -> None:
    """Analytics hook when compaction aligns with cache break (stub)."""
    return
