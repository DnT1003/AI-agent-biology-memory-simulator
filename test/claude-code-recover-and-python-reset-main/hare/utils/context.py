"""Model context window and max-output helpers (`context.ts`)."""

from __future__ import annotations

import os
from typing import Any

from hare.utils.config import get_global_config
from hare.utils.env_utils import is_env_truthy
from hare.utils.model import get_canonical_name

MODEL_CONTEXT_WINDOW_DEFAULT = 200_000
COMPACT_MAX_OUTPUT_TOKENS = 20_000
MAX_OUTPUT_TOKENS_DEFAULT = 32_000
MAX_OUTPUT_TOKENS_UPPER_LIMIT = 64_000
CAPPED_DEFAULT_MAX_TOKENS = 8_000
ESCALATED_MAX_TOKENS = 64_000

# TS uses CONTEXT_1M_BETA_HEADER from constants — use string literal for parity
CONTEXT_1M_BETA_HEADER = "context-1m-2025-08-07"


def _get_model_capability(model: str) -> dict[str, Any] | None:
    try:
        from hare.utils.model.model_capabilities import get_model_capability

        return get_model_capability(model)
    except Exception:
        return None


def _resolve_ant_model(_model: str) -> dict[str, Any] | None:
    """Ant internal model table (stub)."""
    return None


def is_1m_context_disabled() -> bool:
    return is_env_truthy(os.environ.get("CLAUDE_CODE_DISABLE_1M_CONTEXT"))


def has_1m_context(model: str) -> bool:
    if is_1m_context_disabled():
        return False
    return "[1m]" in model.lower()


def model_supports_1m(model: str) -> bool:
    if is_1m_context_disabled():
        return False
    c = get_canonical_name(model)
    return "claude-sonnet-4" in c or "opus-4-6" in c


def get_context_window_for_model(model: str, betas: list[str] | None = None) -> int:
    if os.environ.get("USER_TYPE") == "ant" and os.environ.get("CLAUDE_CODE_MAX_CONTEXT_TOKENS"):
        try:
            override = int(os.environ["CLAUDE_CODE_MAX_CONTEXT_TOKENS"], 10)
            if override > 0:
                return override
        except ValueError:
            pass
    if has_1m_context(model):
        return 1_000_000
    cap = _get_model_capability(model)
    if cap and cap.get("max_input_tokens") and int(cap["max_input_tokens"]) >= 100_000:
        mit = int(cap["max_input_tokens"])
        if mit > MODEL_CONTEXT_WINDOW_DEFAULT and is_1m_context_disabled():
            return MODEL_CONTEXT_WINDOW_DEFAULT
        return mit
    b = betas or []
    if CONTEXT_1M_BETA_HEADER in b and model_supports_1m(model):
        return 1_000_000
    if get_sonnet_1m_exp_treatment_enabled(model):
        return 1_000_000
    if os.environ.get("USER_TYPE") == "ant":
        am = _resolve_ant_model(model)
        if am and am.get("contextWindow"):
            return int(am["contextWindow"])
    return MODEL_CONTEXT_WINDOW_DEFAULT


def get_sonnet_1m_exp_treatment_enabled(model: str) -> bool:
    if is_1m_context_disabled() or has_1m_context(model):
        return False
    if "sonnet-4-6" not in get_canonical_name(model):
        return False
    gc = get_global_config()
    cache = getattr(gc, "client_data_cache", None)
    if not isinstance(cache, dict):
        cache = {}
    return cache.get("coral_reef_sonnet") == "true"


def calculate_context_percentages(
    current_usage: dict[str, int] | None,
    context_window_size: int,
) -> dict[str, int | None]:
    if not current_usage:
        return {"used": None, "remaining": None}
    total = (
        current_usage.get("input_tokens", 0)
        + current_usage.get("cache_creation_input_tokens", 0)
        + current_usage.get("cache_read_input_tokens", 0)
    )
    used_pct = round((total / context_window_size) * 100) if context_window_size else 0
    clamped = min(100, max(0, used_pct))
    return {"used": clamped, "remaining": 100 - clamped}


def get_model_max_output_tokens(model: str) -> dict[str, int]:
    if os.environ.get("USER_TYPE") == "ant":
        am = _resolve_ant_model(model.lower())
        if am:
            return {
                "default": int(am.get("defaultMaxTokens") or MAX_OUTPUT_TOKENS_DEFAULT),
                "upperLimit": int(am.get("upperMaxTokensLimit") or MAX_OUTPUT_TOKENS_UPPER_LIMIT),
            }
    m = get_canonical_name(model)
    if "opus-4-6" in m:
        default_tokens, upper = 64_000, 128_000
    elif "sonnet-4-6" in m:
        default_tokens, upper = 32_000, 128_000
    elif "opus-4-5" in m or ("sonnet-4" in m or "haiku-4" in m):
        default_tokens, upper = 32_000, 64_000
    elif "opus-4-1" in m or "opus-4" in m:
        default_tokens, upper = 32_000, 32_000
    elif "claude-3-opus" in m:
        default_tokens, upper = 4_096, 4_096
    elif "claude-3-sonnet" in m:
        default_tokens, upper = 8_192, 8_192
    elif "claude-3-haiku" in m:
        default_tokens, upper = 4_096, 4_096
    elif "3-5-sonnet" in m or "3-5-haiku" in m:
        default_tokens, upper = 8_192, 8_192
    elif "3-7-sonnet" in m:
        default_tokens, upper = 32_000, 64_000
    else:
        default_tokens, upper = MAX_OUTPUT_TOKENS_DEFAULT, MAX_OUTPUT_TOKENS_UPPER_LIMIT
    cap = _get_model_capability(model)
    if cap and cap.get("max_tokens") and int(cap["max_tokens"]) >= 4_096:
        upper = int(cap["max_tokens"])
        default_tokens = min(default_tokens, upper)
    return {"default": default_tokens, "upperLimit": upper}


def get_max_thinking_tokens_for_model(model: str) -> int:
    o = get_model_max_output_tokens(model)
    return o["upperLimit"] - 1
