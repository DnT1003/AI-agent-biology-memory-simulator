"""MCP tool result size validation — port of `mcpValidation.ts`."""

from __future__ import annotations

from typing import Any

from hare.services.token_estimation import estimate_tokens as rough_token_count_estimation
from hare.utils.log import log_error

MCP_TOKEN_COUNT_THRESHOLD_FACTOR = 0.5
IMAGE_TOKEN_ESTIMATE = 1600
DEFAULT_MAX_MCP_OUTPUT_TOKENS = 25000


def get_feature_value_cached_may_be_stale(_k: str, default: Any) -> Any:
    return default


def get_max_mcp_output_tokens() -> int:
    import os

    raw = os.environ.get("MAX_MCP_OUTPUT_TOKENS")
    if raw:
        try:
            v = int(raw, 10)
            if v > 0:
                return v
        except ValueError:
            pass
    overrides = get_feature_value_cached_may_be_stale("tengu_satin_quoll", {}) or {}
    o = overrides.get("mcp_tool") if isinstance(overrides, dict) else None
    if isinstance(o, (int, float)) and o > 0:
        return int(o)
    return DEFAULT_MAX_MCP_OUTPUT_TOKENS


def get_content_size_estimate(content: str | list[dict[str, Any]] | None) -> int:
    if not content:
        return 0
    if isinstance(content, str):
        return rough_token_count_estimation(content)
    total = 0
    for block in content:
        if block.get("type") == "text":
            total += rough_token_count_estimation(str(block.get("text", "")))
        elif block.get("type") == "image":
            total += IMAGE_TOKEN_ESTIMATE
    return total


async def count_messages_tokens_with_api(_messages: list[Any], _tools: list[Any]) -> int | None:
    """Stub: wire to tokenizer API."""
    return None


def get_truncation_message() -> str:
    return f"\n\n[OUTPUT TRUNCATED - exceeded {get_max_mcp_output_tokens()} token limit]\n\nThe tool output was truncated. If this MCP server provides pagination or filtering tools, use them to retrieve specific portions of the data. If pagination is not available, inform the user that you are working with truncated output and results may be incomplete."


def _max_chars() -> int:
    return get_max_mcp_output_tokens() * 4


def _truncate_string(content: str, max_chars: int) -> str:
    return content if len(content) <= max_chars else content[:max_chars]


async def mcp_content_needs_truncation(content: str | list[dict[str, Any]] | None) -> bool:
    if not content:
        return False
    est = get_content_size_estimate(content)
    if est <= get_max_mcp_output_tokens() * MCP_TOKEN_COUNT_THRESHOLD_FACTOR:
        return False
    try:
        messages = [{"role": "user", "content": content}]
        tc = await count_messages_tokens_with_api(messages, [])
        return bool(tc and tc > get_max_mcp_output_tokens())
    except Exception as e:
        log_error(e if isinstance(e, Exception) else RuntimeError(str(e)))
        return False


async def truncate_mcp_content(content: str | list[dict[str, Any]] | None) -> str | list[dict[str, Any]] | None:
    if not content:
        return content
    mc = _max_chars()
    msg = get_truncation_message()
    if isinstance(content, str):
        return _truncate_string(content, mc) + msg
    out: list[dict[str, Any]] = []
    cur = 0
    for block in content:
        if block.get("type") == "text":
            t = str(block.get("text", ""))
            rem = mc - cur
            if rem <= 0:
                break
            if len(t) <= rem:
                out.append(block)
                cur += len(t)
            else:
                out.append({"type": "text", "text": t[:rem]})
                break
        elif block.get("type") == "image":
            ic = IMAGE_TOKEN_ESTIMATE * 4
            if cur + ic <= mc:
                out.append(block)
                cur += ic
            else:
                break
        else:
            out.append(block)
    out.append({"type": "text", "text": msg})
    return out


async def truncate_mcp_content_if_needed(content: str | list[dict[str, Any]] | None) -> str | list[dict[str, Any]] | None:
    if not await mcp_content_needs_truncation(content):
        return content
    return await truncate_mcp_content(content)
