"""
Token budget tracking for query continuations.

Port of: src/query/tokenBudget.ts
"""

from __future__ import annotations

import time
from dataclasses import dataclass

COMPLETION_THRESHOLD = 0.9
DIMINISHING_THRESHOLD = 500


@dataclass
class BudgetTracker:
    continuation_count: int = 0
    last_delta_tokens: int = 0
    last_global_turn_tokens: int = 0
    started_at: float = 0.0

    def __post_init__(self) -> None:
        if self.started_at == 0.0:
            self.started_at = time.time()


def create_budget_tracker() -> BudgetTracker:
    return BudgetTracker()


@dataclass
class ContinueDecision:
    action: str = "continue"
    nudge_message: str = ""
    continuation_count: int = 0
    pct: int = 0
    turn_tokens: int = 0
    budget: int = 0


@dataclass
class StopDecision:
    action: str = "stop"
    completion_event: dict | None = None


TokenBudgetDecision = ContinueDecision | StopDecision


def _get_budget_continuation_message(pct: int, turn_tokens: int, budget: int) -> str:
    remaining = budget - turn_tokens
    return (
        f"You have used approximately {pct}% of your token budget "
        f"({turn_tokens}/{budget} tokens, ~{remaining} remaining). "
        "Continue working on the task."
    )


def check_token_budget(
    tracker: BudgetTracker,
    agent_id: str | None,
    budget: int | None,
    global_turn_tokens: int,
) -> TokenBudgetDecision:
    if agent_id or budget is None or budget <= 0:
        return StopDecision(completion_event=None)

    turn_tokens = global_turn_tokens
    pct = round((turn_tokens / budget) * 100)
    delta_since_last = global_turn_tokens - tracker.last_global_turn_tokens

    is_diminishing = (
        tracker.continuation_count >= 3
        and delta_since_last < DIMINISHING_THRESHOLD
        and tracker.last_delta_tokens < DIMINISHING_THRESHOLD
    )

    if not is_diminishing and turn_tokens < budget * COMPLETION_THRESHOLD:
        tracker.continuation_count += 1
        tracker.last_delta_tokens = delta_since_last
        tracker.last_global_turn_tokens = global_turn_tokens
        return ContinueDecision(
            nudge_message=_get_budget_continuation_message(pct, turn_tokens, budget),
            continuation_count=tracker.continuation_count,
            pct=pct,
            turn_tokens=turn_tokens,
            budget=budget,
        )

    if is_diminishing or tracker.continuation_count > 0:
        return StopDecision(
            completion_event={
                "continuation_count": tracker.continuation_count,
                "pct": pct,
                "turn_tokens": turn_tokens,
                "budget": budget,
                "diminishing_returns": is_diminishing,
                "duration_ms": int((time.time() - tracker.started_at) * 1000),
            }
        )

    return StopDecision(completion_event=None)
