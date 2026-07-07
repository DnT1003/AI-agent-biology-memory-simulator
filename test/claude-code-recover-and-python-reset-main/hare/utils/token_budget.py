"""Token budget accounting for context windows. Port of: tokenBudget.ts"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TokenBudget:
    max_tokens: int
    used_tokens: int = 0

    @property
    def remaining(self) -> int:
        return max(0, self.max_tokens - self.used_tokens)
