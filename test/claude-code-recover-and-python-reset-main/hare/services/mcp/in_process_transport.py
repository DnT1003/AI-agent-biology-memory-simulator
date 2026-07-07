"""
In-process MCP transport (SDK stub).

Port of: src/services/mcp/InProcessTransport.ts
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class InProcessTransport:
    """Stub transport for embedded MCP servers."""

    name: str = ""

    async def connect(self) -> None:
        return

    async def send(self, _message: dict[str, Any]) -> None:
        return
