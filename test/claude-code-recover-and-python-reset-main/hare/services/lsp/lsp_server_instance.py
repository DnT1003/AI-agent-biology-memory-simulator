"""
Single LSP server lifecycle (stdio/jsonrpc).

Port of: src/services/lsp/LSPServerInstance.ts — protocol-shaped stub.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional


@dataclass
class ScopedLspServerConfig:
    name: str
    command: list[str] = field(default_factory=list)
    cwd: str = ""


LspServerState = str  # "stopped" | "starting" | "running" | "stopping" | "error"


@dataclass
class LspServerInstance:
    name: str
    config: ScopedLspServerConfig
    state: LspServerState = "stopped"
    start_time: Optional[datetime] = None
    last_error: Optional[BaseException] = None
    restart_count: int = 0
    _notifications: dict[str, list[Callable[[Any], None]]] = field(default_factory=dict)

    async def start(self) -> None:
        self.state = "running"
        self.start_time = datetime.utcnow()

    async def stop(self) -> None:
        self.state = "stopped"

    async def restart(self) -> None:
        self.restart_count += 1
        await self.stop()
        await self.start()

    def is_healthy(self) -> bool:
        return self.state == "running"

    async def send_request(self, _method: str, _params: Any) -> Any:
        return None

    async def send_notification(self, _method: str, _params: Any) -> None:
        return

    def on_notification(self, method: str, handler: Callable[[Any], None]) -> None:
        self._notifications.setdefault(method, []).append(handler)

    def on_request(self, method: str, handler: Callable[..., Any]) -> None:
        del method, handler


def create_lsp_server_instance(
    name: str,
    config: ScopedLspServerConfig,
    _create_client: Callable[..., Any],
) -> LspServerInstance:
    return LspServerInstance(name=name, config=config)
