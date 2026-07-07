"""Port of: src/utils/model/deprecation.ts"""
from __future__ import annotations

DEPRECATED_MODELS = frozenset({"claude-2.0", "claude-2.1", "claude-instant-1.2"})

def is_model_deprecated(model: str) -> bool:
    return model in DEPRECATED_MODELS

def get_deprecation_message(model: str) -> str:
    if not is_model_deprecated(model): return ""
    return f"Model {model} is deprecated. Please use a newer model."
