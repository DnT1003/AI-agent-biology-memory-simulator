"""
Automatic compaction when context window is tight.

Port of: src/services/compact/autoCompact.ts — orchestration stub.
"""

from __future__ import annotations

import os
from typing import Any

from hare.services.api.claude import get_max_output_tokens_for_model
from hare.services.compact.compact_full import CompactionResult, compact_conversation

MAX_OUTPUT_TOKENS_FOR_SUMMARY = 20_000


def get_effective_context_window_size(model: str) -> int:
    """Context window minus reserved summary output."""
    reserved = min(get_max_output_tokens_for_model(model), MAX_OUTPUT_TOKENS_FOR_SUMMARY)
    # Stub: real impl uses get_context_window_for_model from utils.context
    window = 200_000
    auto = os.environ.get("CLAUDE_CODE_AUTO_COMPACT_WINDOW")
    if auto:
        try:
            parsed = int(auto, 10)
            if parsed > 0:
                window = min(window, parsed)
        except ValueError:
            pass
    return window - reserved


async def maybe_run_auto_compact(
    messages: list[dict[str, Any]],
    model: str,
) -> CompactionResult | None:
    """Run compaction if over threshold (stub)."""
    del model
    if len(messages) < 2:
        return None
    return await compact_conversation(messages)
