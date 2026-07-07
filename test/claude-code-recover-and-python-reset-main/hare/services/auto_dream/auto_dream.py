"""
Auto-dream: background analysis after each turn.

Port of: src/services/autoDream/autoDream.ts
"""

from __future__ import annotations

from typing import Any, Callable


async def execute_auto_dream(
    hook_context: dict[str, Any],
    append_system_message: Callable[..., Any] | None = None,
) -> None:
    """
    Fire-and-forget background analysis after each turn.
    Stub: full implementation would fork a lightweight model call
    to extract insights from the conversation.
    """
    pass
