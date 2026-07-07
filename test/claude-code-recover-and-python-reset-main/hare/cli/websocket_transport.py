"""WebSocket transport stub (port of src/cli/transports/WebSocketTransport.ts)."""

from __future__ import annotations

from typing import Any, Callable


class WebSocketTransport:
    def __init__(self, url: str, **_kwargs: Any) -> None:
        self._url = url
        self._on_data: Callable[[str], None] | None = None

    async def connect(self) -> None:
        return

    def set_on_data(self, cb: Callable[[str], None]) -> None:
        self._on_data = cb

    async def write(self, _message: Any) -> None:
        return

    def close(self) -> None:
        return
