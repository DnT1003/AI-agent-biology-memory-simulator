"""SSE transport stub (port of src/cli/transports/SSETransport.ts)."""

from __future__ import annotations

from typing import Any, Callable


class SSETransport:
    def __init__(self, url: str, **_kwargs: Any) -> None:
        self._url = url
        self._on_data: Callable[[str], None] | None = None

    async def connect(self) -> None:
        return

    def set_on_data(self, cb: Callable[[str], None]) -> None:
        self._on_data = cb

    def set_on_close(self, _cb: Callable[..., None]) -> None:
        return

    def set_on_event(self, _cb: Callable[..., None]) -> None:
        return

    async def write(self, _message: Any) -> None:
        return

    def close(self) -> None:
        return
