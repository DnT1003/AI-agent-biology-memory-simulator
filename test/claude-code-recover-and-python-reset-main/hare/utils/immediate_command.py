"""Whether /model, /fast, /effort run immediately during a query — port of `immediateCommand.ts`."""

from __future__ import annotations

import os


def get_feature_value_cached_may_be_stale(_key: str, default: bool) -> bool:
    """Stub: wire to GrowthBook / experiments."""
    return default


def should_inference_config_command_be_immediate() -> bool:
    return os.environ.get("USER_TYPE") == "ant" or get_feature_value_cached_may_be_stale(
        "tengu_immediate_model_command", False
    )
