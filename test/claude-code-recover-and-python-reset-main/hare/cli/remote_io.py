"""Remote structured IO (port of src/cli/remoteIO.ts)."""

from __future__ import annotations

from typing import Any


class RemoteIO:
    """Bidirectional streaming for SDK mode — full wiring uses transports + CCR."""

    def __init__(self, stream_url: str, **_kwargs: Any) -> None:
        self._url = stream_url

    async def write(self, _message: Any) -> None:
        return

    async def flush_internal_events(self) -> None:
        return

    @property
    def internal_events_pending(self) -> int:
        return 0

    def close(self) -> None:
        return
