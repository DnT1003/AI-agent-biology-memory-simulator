"""
Validate model strings against allowlist and optional API probe.

Port of: src/utils/model/validateModel.ts
"""

from __future__ import annotations

import os
from typing import Any

from hare.utils.model.aliases import is_model_alias
from hare.utils.model.model_allowlist import is_model_allowed


_valid_model_cache: dict[str, bool] = {}


async def _side_query(_payload: dict[str, Any]) -> None:
    """Stub for ../sideQuery.sideQuery (optional API probe)."""
    del _payload
    return None


def _handle_validation_error(error: BaseException, model: str) -> dict[str, bool | str]:
    name = type(error).__name__
    return {"valid": False, "error": f"{name} for model {model!r}: {error}"}


async def validate_model(model: str) -> dict[str, bool | str]:
    normalized = model.strip()
    if not normalized:
        return {"valid": False, "error": "Model name cannot be empty"}

    if not is_model_allowed(normalized):
        return {
            "valid": False,
            "error": f"Model {normalized!r} is not in the list of available models",
        }

    if is_model_alias(normalized):
        return {"valid": True}

    custom = os.environ.get("ANTHROPIC_CUSTOM_MODEL_OPTION")
    if custom and normalized == custom:
        return {"valid": True}

    if normalized in _valid_model_cache:
        return {"valid": True}

    try:
        await _side_query(
            {
                "model": normalized,
                "max_tokens": 1,
                "maxRetries": 0,
                "querySource": "model_validation",
                "messages": [{"role": "user", "content": [{"type": "text", "text": "Hi"}]}],
            }
        )
    except Exception as e:
        return _handle_validation_error(e, normalized)
    _valid_model_cache[normalized] = True
    return {"valid": True}


def clear_validation_cache() -> None:
    _valid_model_cache.clear()
