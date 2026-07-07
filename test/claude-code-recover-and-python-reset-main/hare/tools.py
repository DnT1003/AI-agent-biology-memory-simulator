"""
Tool registry and tool pool assembly.

Port of: src/tools.ts

This is the central registry for all built-in tools. It maps exactly
to getAllBaseTools() / getTools() / assembleToolPool() in the TS source.
"""

from __future__ import annotations

import importlib
import os
from typing import Any, Sequence

from hare.tool import Tool, ToolBase, ToolResult, ToolUseContext, Tools, tool_matches_name
from hare.types.permissions import ToolPermissionContext, ToolPermissionRulesBySource
from hare.utils.env_utils import is_env_truthy

ALL_AGENT_DISALLOWED_TOOLS: list[str] = []
CUSTOM_AGENT_DISALLOWED_TOOLS: list[str] = []
ASYNC_AGENT_ALLOWED_TOOLS: list[str] = []
COORDINATOR_MODE_ALLOWED_TOOLS: list[str] = []

TOOL_PRESETS = ("default",)


def _wrap_module_tool(module_path: str, tool_name: str, **overrides: Any) -> ToolBase:
    """Wrap a function-based tool module into a ToolBase singleton."""
    mod = importlib.import_module(module_path)

    class _Wrapped(ToolBase):
        name = tool_name
        aliases = getattr(mod, "ALIASES", [])
        search_hint = getattr(mod, "SEARCH_HINT", tool_name)

        def input_schema(self) -> dict[str, Any]:
            return mod.input_schema()

        def is_read_only(self, input: dict[str, Any]) -> bool:
            fn = getattr(mod, "is_read_only", None)
            if fn:
                return fn(input)
            return overrides.get("read_only", False)

        async def call(self, args: dict[str, Any], context: Any = None, **kw: Any) -> ToolResult:
            result = await mod.call(**args)
            return ToolResult(data=result)

    return _Wrapped()


def parse_tool_preset(preset: str) -> str | None:
    lower = preset.lower()
    if lower in TOOL_PRESETS:
        return lower
    return None


def get_tools_for_default_preset() -> list[str]:
    tools = get_all_base_tools()
    return [t.name for t in tools if t.is_enabled()]


def get_all_base_tools() -> list[Tool]:
    """
    Get all tools. Class-based tools are imported directly;
    function-based tool modules are wrapped via _wrap_module_tool.
    """
    from hare.tools_impl.BashTool.bash_tool import BashTool
    from hare.tools_impl.AgentTool.agent_tool import AgentTool
    from hare.tools_impl.TodoWriteTool.todo_write_tool import TodoWriteTool

    FileReadTool = _wrap_module_tool(
        "hare.tools_impl.FileReadTool.file_read_tool", "Read", read_only=True)
    FileEditTool = _wrap_module_tool(
        "hare.tools_impl.FileEditTool.file_edit_tool", "Edit")
    FileWriteTool = _wrap_module_tool(
        "hare.tools_impl.FileWriteTool.file_write_tool", "Write")
    GlobTool = _wrap_module_tool(
        "hare.tools_impl.GlobTool.glob_tool", "Glob", read_only=True)
    GrepTool = _wrap_module_tool(
        "hare.tools_impl.GrepTool.grep_tool", "Grep", read_only=True)
    WebFetchTool = _wrap_module_tool(
        "hare.tools_impl.WebFetchTool.web_fetch_tool", "WebFetch", read_only=True)
    WebSearchTool = _wrap_module_tool(
        "hare.tools_impl.WebSearchTool.web_search_tool", "WebSearch", read_only=True)

    tools: list[Tool] = [
        AgentTool,
        BashTool,
        GlobTool,
        GrepTool,
        FileReadTool,
        FileEditTool,
        FileWriteTool,
        WebFetchTool,
        TodoWriteTool,
        WebSearchTool,
    ]
    return tools


def _get_deny_rule_for_tool(
    permission_context: ToolPermissionContext, tool: Any
) -> bool:
    """Check if a tool is blanket-denied by the permission context."""
    deny_rules = permission_context.always_deny_rules
    for _source, rules in deny_rules.items():
        for rule in rules:
            if tool_matches_name(tool, rule):
                return True
    return False


def filter_tools_by_deny_rules(
    tools: Sequence[Tool], permission_context: ToolPermissionContext
) -> list[Tool]:
    """
    Filters out tools that are blanket-denied by the permission context.
    A tool is filtered out if there's a deny rule matching its name with no
    ruleContent (i.e., a blanket deny for that tool).
    """
    return [t for t in tools if not _get_deny_rule_for_tool(permission_context, t)]


def get_tools(permission_context: ToolPermissionContext) -> list[Tool]:
    """
    Get tools filtered for the given permission context.

    Simple mode (CLAUDE_CODE_SIMPLE): only Bash, Read, and Edit tools.
    """
    if is_env_truthy(os.environ.get("CLAUDE_CODE_SIMPLE")):
        from hare.tools_impl.BashTool.bash_tool import BashTool

        FileReadTool = _wrap_module_tool(
            "hare.tools_impl.FileReadTool.file_read_tool", "Read", read_only=True)
        FileEditTool = _wrap_module_tool(
            "hare.tools_impl.FileEditTool.file_edit_tool", "Edit")
        return filter_tools_by_deny_rules(
            [BashTool, FileReadTool, FileEditTool], permission_context
        )

    all_tools = get_all_base_tools()
    allowed = filter_tools_by_deny_rules(all_tools, permission_context)
    return [t for t in allowed if t.is_enabled()]


def assemble_tool_pool(
    permission_context: ToolPermissionContext,
    mcp_tools: list[Tool] | None = None,
) -> list[Tool]:
    """
    Assemble the full tool pool for a given permission context and MCP tools.

    This is the single source of truth for combining built-in tools with MCP tools.
    """
    built_in = get_tools(permission_context)
    if not mcp_tools:
        return sorted(built_in, key=lambda t: t.name)

    allowed_mcp = filter_tools_by_deny_rules(mcp_tools, permission_context)
    # Built-in tools take precedence over MCP tools by name
    built_in_names = {t.name for t in built_in}
    deduped_mcp = [t for t in allowed_mcp if t.name not in built_in_names]

    return sorted(built_in, key=lambda t: t.name) + sorted(
        deduped_mcp, key=lambda t: t.name
    )


def get_merged_tools(
    permission_context: ToolPermissionContext,
    mcp_tools: list[Tool] | None = None,
) -> list[Tool]:
    """Get all tools including both built-in tools and MCP tools."""
    built_in = get_tools(permission_context)
    if not mcp_tools:
        return built_in
    return [*built_in, *mcp_tools]
