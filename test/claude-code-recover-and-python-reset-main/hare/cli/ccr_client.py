"""CCR v2 client stub (port of src/cli/transports/ccrClient.ts)."""

from __future__ import annotations

from typing import Any, Literal

CCRInitFailReason = Literal["no_auth_headers", "missing_epoch", "worker_register_failed"]


class CCRInitError(Exception):
    def __init__(self, reason: CCRInitFailReason) -> None:
        super().__init__(f"CCRClient init failed: {reason}")
        self.reason = reason


class CCRClient:
    def __init__(self, _transport: Any, _session_url: Any, **_opts: Any) -> None:
        pass

    async def initialize(self, _epoch: int | None = None) -> dict[str, Any] | None:
        return None

    async def write_event(self, _message: Any) -> None:
        return

    async def write_internal_event(
        self,
        _event_type: str,
        _payload: dict[str, Any],
        **_opts: Any,
    ) -> None:
        return

    async def flush_internal_events(self) -> None:
        return

    @property
    def internal_events_pending(self) -> int:
        return 0

    def close(self) -> None:
        return
