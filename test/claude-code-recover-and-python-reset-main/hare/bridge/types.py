"""
Bridge types and constants.

Port of: src/bridge/types.ts
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

DEFAULT_SESSION_TIMEOUT_MS = 300_000
BRIDGE_LOGIN_PATH = "/v1/environments/bridge"
REMOTE_CONTROL_DISCONNECTED_MSG = "Remote control disconnected"

SessionDoneStatus = Literal["completed", "cancelled", "error", "timeout"]
SpawnMode = Literal["fork", "process"]
BridgeWorkerType = Literal["session", "heartbeat"]


@dataclass
class WorkSecret:
    session_id: str = ""
    access_token: str = ""
    sdk_url: str = ""
    bridge_id: str = ""


@dataclass
class WorkData:
    work_id: str = ""
    session_id: str = ""
    secret: WorkSecret = field(default_factory=WorkSecret)
    prompt: str = ""
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkResponse:
    status: str = ""
    work: WorkData | None = None
    retry_after_ms: int = 0


@dataclass
class BridgeConfig:
    base_url: str = ""
    access_token: str = ""
    bridge_id: str = ""
    organization_uuid: str = ""
    poll_interval_ms: int = 5000
    heartbeat_interval_ms: int = 30000
    max_concurrent_sessions: int = 1


@dataclass
class SessionActivity:
    type: str = ""
    timestamp: float = 0.0
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class PermissionResponseEvent:
    request_id: str = ""
    approved: bool = False
    reason: str = ""


class SessionHandle(Protocol):
    async def send(self, message: str) -> None: ...
    async def stop(self) -> None: ...
    @property
    def is_running(self) -> bool: ...


class SessionSpawner(Protocol):
    async def spawn(self, work: WorkData) -> SessionHandle: ...


class BridgeLogger(Protocol):
    def info(self, msg: str) -> None: ...
    def error(self, msg: str) -> None: ...
    def debug(self, msg: str) -> None: ...
