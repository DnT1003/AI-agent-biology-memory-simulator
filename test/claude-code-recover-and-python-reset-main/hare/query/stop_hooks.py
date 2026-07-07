"""
Stop hooks handling after each query turn.

Port of: src/query/stopHooks.ts
"""

from __future__ import annotations

from typing import Any, AsyncGenerator


async def handle_stop_hooks(
    messages_for_query: list[dict[str, Any]],
    assistant_messages: list[dict[str, Any]],
    system_prompt: str,
    user_context: dict[str, str],
    system_context: dict[str, str],
    tool_use_context: Any,
    query_source: str,
    stop_hook_active: bool = False,
) -> AsyncGenerator[dict[str, Any], None]:
    """
    Run stop hooks after a turn completes.
    Yields messages/events. Returns blocking errors and prevention state.

    Stub: full implementation handles executeStopHooks,
    TeammateIdle, TaskCompleted, extract memories, auto-dream, etc.
    """
    return
    yield  # type: ignore[misc]


class StopHookResult:
    def __init__(
        self,
        blocking_errors: list[dict[str, Any]] | None = None,
        prevent_continuation: bool = False,
    ) -> None:
        self.blocking_errors = blocking_errors or []
        self.prevent_continuation = prevent_continuation
