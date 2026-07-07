"""Doctor /context warnings (`doctorContextWarnings.ts`). — stub."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ContextWarning:
    type: str
    severity: str
    message: str
    details: list[str]
    current_value: int
    threshold: int


@dataclass
class ContextWarnings:
    claude_md_warning: ContextWarning | None
    agent_warning: ContextWarning | None
    mcp_warning: ContextWarning | None
    unreachable_rules_warning: ContextWarning | None


async def check_context_warnings(
    tools: list[Any],
    agent_info: Any,
    get_tool_permission_context: Any,
) -> ContextWarnings:
    return ContextWarnings(None, None, None, None)
