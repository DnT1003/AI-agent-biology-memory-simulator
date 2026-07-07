"""Orchestrate persisting output files to remote storage. Port of: filePersistence.ts"""

from __future__ import annotations

import os
from typing import Any


async def run_file_persistence(
    _turn_start_time: Any,
    _signal: Any | None = None,
) -> dict[str, Any] | None:
    """BYOC upload path — stub returns None when not enabled."""
    if os.environ.get("CLAUDE_CODE_ENVIRONMENT_KIND") != "byoc":
        return None
    return None
