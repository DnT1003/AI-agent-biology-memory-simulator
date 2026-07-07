"""Hybrid WS+POST transport stub (port of src/cli/transports/HybridTransport.ts)."""

from __future__ import annotations

from typing import Any


class HybridTransport:
    def __init__(self, url: str, **_kwargs: Any) -> None:
        self._url = url

    async def connect(self) -> None:
        return

    async def write(self, _message: Any) -> None:
        return

    def close(self) -> None:
        return
