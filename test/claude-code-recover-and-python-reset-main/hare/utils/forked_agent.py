"""
Forked / subagent query loop orchestration (types and stubs).

Port of: src/utils/forkedAgent.ts — wire `query`, analytics, and ToolUseContext at integration.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, TypeVar, runtime_checkable

from hare.utils.file_state_cache import FileStateCache, clone_file_state_cache

T = TypeVar("T")


@dataclass
class CacheSafeParams:
    system_prompt: Any
    user_context: dict[str, str]
    system_context: dict[str, str]
    tool_use_context: Any
    fork_context_messages: list[Any]


_last_cache_safe: CacheSafeParams | None = None


def save_cache_safe_params(params: CacheSafeParams | None) -> None:
    global _last_cache_safe
    _last_cache_safe = params


def get_last_cache_safe_params() -> CacheSafeParams | None:
    return _last_cache_safe


@dataclass
class ForkedAgentParams:
    prompt_messages: list[Any]
    cache_safe_params: CacheSafeParams
    can_use_tool: Callable[..., Any]
    query_source: str
    fork_label: str
    overrides: Any | None = None
    max_output_tokens: int | None = None
    max_turns: int | None = None
    on_message: Callable[[Any], None] | None = None
    skip_transcript: bool = False
    skip_cache_write: bool = False


@dataclass
class ForkedAgentResult:
    messages: list[Any]
    total_usage: dict[str, int]


def create_cache_safe_params(context: Any) -> CacheSafeParams:
    return CacheSafeParams(
        system_prompt=context.system_prompt,
        user_context=context.user_context,
        system_context=context.system_context,
        tool_use_context=context.tool_use_context,
        fork_context_messages=context.messages,
    )


def create_get_app_state_with_allowed_tools(
    base_get_app_state: Callable[[], Any],
    allowed_tools: list[str],
) -> Callable[[], Any]:
    if not allowed_tools:
        return base_get_app_state

    def wrapped() -> Any:
        app_state = base_get_app_state()
        tpc = getattr(app_state, "tool_permission_context", None) or app_state.get(
            "tool_permission_context"
        )
        if tpc is None:
            return app_state
        rules = dict(getattr(tpc, "always_allow_rules", None) or tpc.get("always_allow_rules") or {})
        cmds = list(rules.get("command", []) or [])
        rules["command"] = list(dict.fromkeys([*cmds, *allowed_tools]))
        if isinstance(app_state, dict):
            out = {**app_state, "tool_permission_context": {**tpc, "always_allow_rules": rules}}
            return out
        return app_state

    return wrapped


@dataclass
class PreparedForkedContext:
    skill_content: str
    modified_get_app_state: Callable[[], Any]
    base_agent: Any
    prompt_messages: list[Any]


async def prepare_forked_command_context(
    command: Any,
    args: str,
    context: Any,
) -> PreparedForkedContext:
    skill_prompt = await command.get_prompt_for_command(args, context)
    parts: list[str] = []
    for block in skill_prompt:
        if getattr(block, "type", None) == "text" or (
            isinstance(block, dict) and block.get("type") == "text"
        ):
            t = getattr(block, "text", None) or (block.get("text") if isinstance(block, dict) else "")
            parts.append(str(t))
    skill_content = "\n".join(parts)
    allowed: list[str] = list(getattr(command, "allowed_tools", None) or [])
    modified = create_get_app_state_with_allowed_tools(context.get_app_state, allowed)
    agent_type = getattr(command, "agent", None) or "general-purpose"
    agents = getattr(getattr(context.options, "agent_definitions", None), "active_agents", None) or []
    base_agent = next(
        (a for a in agents if getattr(a, "agent_type", None) == agent_type),
        None,
    )
    if base_agent is None:
        base_agent = next((a for a in agents if getattr(a, "agent_type", None) == "general-purpose"), None)
    if base_agent is None and agents:
        base_agent = agents[0]
    if base_agent is None:
        raise RuntimeError("No agent available for forked execution")
    prompt_messages = [{"type": "user", "message": {"content": skill_content}}]
    return PreparedForkedContext(
        skill_content=skill_content,
        modified_get_app_state=modified,
        base_agent=base_agent,
        prompt_messages=prompt_messages,
    )


def extract_result_text(agent_messages: list[Any], default_text: str = "Execution completed") -> str:
    # Stub: use last assistant text — real implementation uses messages helpers
    if not agent_messages:
        return default_text
    return default_text


def create_subagent_context(parent_context: Any, overrides: dict[str, Any] | None = None) -> Any:
    """Minimal isolation shell; extend when ToolUseContext is ported."""
    ov = overrides or {}
    read_state = ov.get("read_file_state", parent_context.read_file_state)
    if isinstance(read_state, FileStateCache):
        rfs = clone_file_state_cache(read_state)
    else:
        rfs = read_state
    return SimpleNamespace(
        read_file_state=rfs,
        abort_controller=ov.get("abort_controller", getattr(parent_context, "abort_controller", None)),
        get_app_state=ov.get("get_app_state", parent_context.get_app_state),
        set_app_state=ov.get("share_set_app_state") and parent_context.set_app_state or (lambda *_: None),
        options=ov.get("options", parent_context.options),
        messages=ov.get("messages", parent_context.messages),
        agent_id=ov.get("agent_id", str(uuid.uuid4())),
        query_tracking={
            "chainId": str(uuid.uuid4()),
            "depth": (getattr(parent_context.query_tracking, "depth", -1) + 1)
            if hasattr(parent_context, "query_tracking")
            else 0,
        },
    )


class SimpleNamespace:
    def __init__(self, **kwargs: Any) -> None:
        self.__dict__.update(kwargs)

    def clear(self) -> None:
        if hasattr(self, "read_file_state") and hasattr(self.read_file_state, "clear"):
            self.read_file_state.clear()


async def run_forked_agent(params: ForkedAgentParams) -> ForkedAgentResult:
    raise NotImplementedError("Wire hare.query and usage accounting to enable run_forked_agent")
