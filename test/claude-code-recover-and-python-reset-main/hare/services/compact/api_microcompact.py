"""
API-native context management strategies (clear_tool_uses, thinking).

Port of: src/services/compact/apiMicrocompact.ts
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal, Optional, Union


DEFAULT_MAX_INPUT_TOKENS = 180_000
DEFAULT_TARGET_INPUT_TOKENS = 40_000

TOOLS_CLEARABLE_RESULTS: list[str] = []  # filled at runtime from tool name constants in TS
TOOLS_CLEARABLE_USES: list[str] = []


def _env_truthy(name: str) -> bool:
    v = os.environ.get(name, "")
    return v.lower() in ("1", "true", "yes", "on")


@dataclass
class ContextManagementConfig:
    edits: list[dict[str, Any]]


def get_api_context_management(
    *,
    has_thinking: bool = False,
    is_redact_thinking_active: bool = False,
    clear_all_thinking: bool = False,
) -> Optional[ContextManagementConfig]:
    strategies: list[dict[str, Any]] = []

    if has_thinking and not is_redact_thinking_active:
        keep: Union[Literal["all"], dict[str, Any]] = (
            {"type": "thinking_turns", "value": 1} if clear_all_thinking else "all"
        )
        strategies.append({"type": "clear_thinking_20251015", "keep": keep})

    if os.environ.get("USER_TYPE") != "ant":
        return ContextManagementConfig(edits=strategies) if strategies else None

    use_clear_tool_results = _env_truthy("USE_API_CLEAR_TOOL_RESULTS")
    use_clear_tool_uses = _env_truthy("USE_API_CLEAR_TOOL_USES")
    if not use_clear_tool_results and not use_clear_tool_uses:
        return ContextManagementConfig(edits=strategies) if strategies else None

    trigger = int(os.environ.get("API_MAX_INPUT_TOKENS") or DEFAULT_MAX_INPUT_TOKENS)
    keep_target = int(os.environ.get("API_TARGET_INPUT_TOKENS") or DEFAULT_TARGET_INPUT_TOKENS)

    if use_clear_tool_results:
        strategies.append(
            {
                "type": "clear_tool_uses_20250919",
                "trigger": {"type": "input_tokens", "value": trigger},
                "clear_at_least": {"type": "input_tokens", "value": trigger - keep_target},
                "clear_tool_inputs": TOOLS_CLEARABLE_RESULTS,
            }
        )
    if use_clear_tool_uses:
        strategies.append(
            {
                "type": "clear_tool_uses_20250919",
                "trigger": {"type": "input_tokens", "value": trigger},
                "clear_at_least": {"type": "input_tokens", "value": trigger - keep_target},
                "exclude_tools": TOOLS_CLEARABLE_USES,
            }
        )

    return ContextManagementConfig(edits=strategies) if strategies else None
