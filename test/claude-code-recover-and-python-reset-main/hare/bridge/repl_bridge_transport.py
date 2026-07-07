"""Port of: src/bridge/replBridgeTransport.ts"""
from __future__ import annotations
from typing import Any, Protocol

class ReplBridgeTransport(Protocol):
    async def send(self, data: Any) -> None: ...
    async def close(self) -> None: ...

async def create_v1_repl_transport(config: Any) -> Any:
    return None

async def create_v2_repl_transport(config: Any) -> Any:
    return None
