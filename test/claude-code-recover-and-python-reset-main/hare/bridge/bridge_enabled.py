"""
Bridge feature flags.

Port of: src/bridge/bridgeEnabled.ts
"""
from __future__ import annotations
import os


def is_bridge_enabled() -> bool:
    return os.environ.get("CLAUDE_CODE_BRIDGE_ENABLED", "").lower() in ("1", "true")


def is_env_less_bridge_enabled() -> bool:
    return os.environ.get("CLAUDE_CODE_ENVLESS_BRIDGE", "").lower() in ("1", "true")


def is_cse_shim_enabled() -> bool:
    return os.environ.get("CLAUDE_CODE_CSE_SHIM", "").lower() in ("1", "true")


def get_bridge_disabled_reason() -> str | None:
    if not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("CLAUDE_CODE_BRIDGE_TOKEN"):
        return "No API key or bridge token configured"
    return None
