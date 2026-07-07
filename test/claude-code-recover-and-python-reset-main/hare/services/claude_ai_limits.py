"""Claude.ai subscription limits snapshot. Port of: src/services/claudeAiLimits.ts"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ClaudeAiLimits:
    max_tokens_per_day: int | None = None


async def fetch_claude_ai_limits() -> ClaudeAiLimits:
    return ClaudeAiLimits()
