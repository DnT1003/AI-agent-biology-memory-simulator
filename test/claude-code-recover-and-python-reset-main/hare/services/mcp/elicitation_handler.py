"""
MCP elicitation request handling (URL / form flows).

Port of: src/services/mcp/elicitationHandler.ts
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal, Optional


@dataclass
class ElicitationWaitingState:
    action_label: str
    show_cancel: bool = False


@dataclass
class ElicitationRequestEvent:
    server_name: str
    request_id: str | int
    params: dict[str, Any]
    respond: Callable[[dict[str, Any]], None]
    waiting_state: Optional[ElicitationWaitingState] = None
    on_waiting_dismiss: Optional[Callable[[Literal["dismiss", "retry", "cancel"]], None]] = None
    completed: bool = False


_elicitation_queue: list[ElicitationRequestEvent] = []


def get_elicitation_queue() -> list[ElicitationRequestEvent]:
    return _elicitation_queue


async def run_elicitation_hooks(
    _server_name: str,
    _params: dict[str, Any],
    _signal: Any,
) -> dict[str, Any] | None:
    return None


async def run_elicitation_result_hooks(
    _server_name: str,
    _result: dict[str, Any],
) -> None:
    return


def register_elicitation_handler_stub(_client: Any, server_name: str) -> None:
    """Placeholder for SDK client.setRequestHandler(ElicitRequestSchema, ...)."""
    del server_name
