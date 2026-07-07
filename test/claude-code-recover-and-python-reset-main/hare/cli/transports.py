"""
CLI transports – stdio and NDJSON.

Port of: src/cli/transports/
"""
from __future__ import annotations
import json, sys
from typing import Any, AsyncIterator, Protocol


class Transport(Protocol):
    async def read(self) -> str | None: ...
    async def write(self, data: str) -> None: ...
    async def close(self) -> None: ...


class StdioTransport:
    async def read(self) -> str | None:
        try:
            line = sys.stdin.readline()
            return line.rstrip("\n") if line else None
        except EOFError:
            return None

    async def write(self, data: str) -> None:
        sys.stdout.write(data + "\n")
        sys.stdout.flush()

    async def close(self) -> None:
        pass


class NdjsonTransport:
    def __init__(self, input_stream: Any = None, output_stream: Any = None):
        self._input = input_stream or sys.stdin
        self._output = output_stream or sys.stdout

    async def read(self) -> dict[str, Any] | None:
        try:
            line = self._input.readline()
            if not line:
                return None
            return json.loads(line)
        except (json.JSONDecodeError, EOFError):
            return None

    async def write(self, data: Any) -> None:
        self._output.write(json.dumps(data, separators=(",", ":")) + "\n")
        self._output.flush()

    async def close(self) -> None:
        pass


class SSETransport:
    def __init__(self, url: str = "", headers: dict[str, str] | None = None):
        self.url = url
        self.headers = headers or {}

    async def connect(self) -> None:
        pass

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        return
        yield  # type: ignore

    async def close(self) -> None:
        pass
