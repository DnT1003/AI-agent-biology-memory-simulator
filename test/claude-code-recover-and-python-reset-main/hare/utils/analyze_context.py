"""
Context window breakdown for `/context` UI (`analyzeContext.ts`).

Full token accounting depends on compaction, tools, and API counters. This
module defines the public datatypes and entrypoints; wire services to match TS.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

TOOL_TOKEN_COUNT_OVERHEAD = 500


@dataclass
class ContextCategory:
    name: str
    tokens: int
    color: str
    is_deferred: bool = False


@dataclass
class GridSquare:
    color: str
    is_filled: bool
    category_name: str
    tokens: int
    percentage: int
    square_fullness: float


@dataclass
class ContextData:
    categories: list[ContextCategory] = field(default_factory=list)
    total_tokens: int = 0
    max_tokens: int = 0
    raw_max_tokens: int = 0
    percentage: int = 0
    grid_rows: list[list[GridSquare]] = field(default_factory=list)
    model: str = ""
    memory_files: list[dict[str, Any]] = field(default_factory=list)
    mcp_tools: list[dict[str, Any]] = field(default_factory=list)
    deferred_builtin_tools: list[dict[str, Any]] | None = None
    system_tools: list[dict[str, Any]] | None = None
    system_prompt_sections: list[dict[str, Any]] | None = None
    agents: list[dict[str, Any]] = field(default_factory=list)
    slash_commands: dict[str, Any] | None = None
    skills: dict[str, Any] | None = None
    auto_compact_threshold: int | None = None
    is_auto_compact_enabled: bool = False
    message_breakdown: dict[str, Any] | None = None
    api_usage: dict[str, int] | None = None


async def analyze_context_usage(
    messages: list[Any],
    model: str,
    get_tool_permission_context: Any,
    tools: list[Any],
    agent_definitions: Any,
    terminal_width: int | None = None,
    tool_use_context: Any | None = None,
    main_thread_agent_definition: Any | None = None,
    original_messages: list[Any] | None = None,
) -> ContextData:
    del (
        messages,
        model,
        get_tool_permission_context,
        tools,
        agent_definitions,
        terminal_width,
        tool_use_context,
        main_thread_agent_definition,
        original_messages,
    )
    raise NotImplementedError("analyze_context_usage: port token estimators and grid builder")


async def count_tool_definition_tokens(
    tools: list[Any],
    get_tool_permission_context: Any,
    agent_info: Any | None,
    model: str | None = None,
) -> int:
    del tools, get_tool_permission_context, agent_info, model
    return 0
