"""
Anthropic Messages API integration (streaming, tools, cache control).

Port of: src/services/api/claude.ts — facade stub; TS source is very large.
"""

from __future__ import annotations

import os
from typing import Any


def _parse_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw, 10)
    except ValueError:
        return default


def get_max_output_tokens_for_model(model: str) -> int:
    """Effective max output tokens for a model (env override wins)."""
    del model
    return _parse_int_env("CLAUDE_CODE_MAX_OUTPUT_TOKENS", 8192)


async def stream_message_beta(_params: dict[str, Any]) -> Any:
    """Stub streaming entrypoint."""
    return None
