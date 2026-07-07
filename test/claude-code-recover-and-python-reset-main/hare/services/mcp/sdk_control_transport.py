"""
SDK-controlled MCP transport (stub).

Port of: src/services/mcp/SdkControlTransport.ts
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class SdkControlTransport:
    session_id: str = ""

    async def connect(self) -> None:
        return

    async def close(self) -> None:
        return

    async def request(self, _method: str, _params: dict[str, Any] | None = None) -> Any:
        return None
