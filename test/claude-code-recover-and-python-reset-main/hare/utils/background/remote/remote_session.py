"""Remote session lifecycle.

Port of: src/utils/background/remote/remoteSession.ts
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RemoteSession:
    session_id: str
    metadata: dict[str, Any] = field(default_factory=dict)


async def start_remote_session(_opts: dict[str, Any]) -> RemoteSession:
    return RemoteSession(session_id="stub")


async def stop_remote_session(_session: RemoteSession) -> None:
    return None
