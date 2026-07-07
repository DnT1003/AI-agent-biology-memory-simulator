"""Disk cache for remote managed settings. Port of: src/services/remoteManagedSettings/syncCache.ts"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hare.services.remote_managed_settings.types import RemoteManagedSettingsPayload


async def read_sync_cache(_path: Path) -> RemoteManagedSettingsPayload | None:
    return None


async def write_sync_cache(_path: Path, _payload: RemoteManagedSettingsPayload) -> None:
    return
