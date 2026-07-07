"""Port of: src/utils/tokens.ts"""
from __future__ import annotations
from typing import Any
from hare.services.token_estimation import estimate_tokens

def get_token_usage(messages: list[dict[str, Any]]) -> dict[str, int]:
    total = 0
    for m in messages:
        c = m.get("message", {}).get("content", "")
        total += estimate_tokens(c if isinstance(c, str) else str(c))
    return {"total": total, "estimated": True}

def token_count_with_estimation(text: str) -> int:
    return estimate_tokens(text)

def token_count_from_last_api_response(response: dict[str, Any]) -> dict[str, int]:
    usage = response.get("usage", {})
    return {
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
    }
