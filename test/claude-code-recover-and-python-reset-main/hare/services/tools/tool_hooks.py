"""
Tool use hooks: pre/post tool execution hooks.

Port of: src/services/tools/toolHooks.ts
"""

from __future__ import annotations

from typing import Any, AsyncGenerator


async def run_pre_tool_use_hooks(
    tool_use_context: Any,
    tool: Any,
    processed_input: dict[str, Any],
    tool_use_id: str,
    message_id: str,
    request_id: str | None = None,
    mcp_server_type: str | None = None,
    mcp_server_base_url: str | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """Run PreToolUse hooks and yield results."""
    # Stub: yield nothing by default
    return
    yield  # type: ignore[misc]


async def run_post_tool_use_hooks(
    tool_use_context: Any,
    tool: Any,
    tool_use_id: str,
    message_id: str,
    tool_input: dict[str, Any],
    tool_response: Any,
    request_id: str | None = None,
    mcp_server_type: str | None = None,
    mcp_server_base_url: str | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """Run PostToolUse hooks and yield results."""
    return
    yield  # type: ignore[misc]


async def run_post_tool_use_failure_hooks(
    tool_use_context: Any,
    tool: Any,
    tool_use_id: str,
    message_id: str,
    processed_input: dict[str, Any],
    error: str,
    is_interrupt: bool | None = None,
    request_id: str | None = None,
    mcp_server_type: str | None = None,
    mcp_server_base_url: str | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """Run PostToolUseFailure hooks and yield results."""
    return
    yield  # type: ignore[misc]


async def resolve_hook_permission_decision(
    hook_permission_result: dict[str, Any] | None,
    tool: Any,
    input_args: dict[str, Any],
    tool_use_context: Any,
    can_use_tool: Any,
    assistant_message: Any,
    tool_use_id: str,
) -> dict[str, Any]:
    """Resolve a PreToolUse hook's permission result into a final PermissionDecision."""
    if hook_permission_result is None:
        return {"decision": {"behavior": "passthrough"}, "input": input_args}

    behavior = hook_permission_result.get("behavior")

    if behavior == "allow":
        updated = hook_permission_result.get("updatedInput", input_args)
        return {"decision": hook_permission_result, "input": updated}

    if behavior == "deny":
        return {"decision": hook_permission_result, "input": input_args}

    return {"decision": {"behavior": "passthrough"}, "input": input_args}
