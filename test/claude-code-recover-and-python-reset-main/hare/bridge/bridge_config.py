"""
Bridge configuration from environment.

Port of: src/bridge/bridgeConfig.ts
"""
from __future__ import annotations
import os


def get_bridge_token_override() -> str | None:
    return os.environ.get("CLAUDE_CODE_BRIDGE_TOKEN")


def get_bridge_base_url_override() -> str | None:
    return os.environ.get("CLAUDE_CODE_BRIDGE_BASE_URL")


def get_bridge_access_token() -> str:
    return get_bridge_token_override() or os.environ.get("ANTHROPIC_API_KEY", "")


def get_bridge_base_url() -> str:
    return get_bridge_base_url_override() or "https://api.anthropic.com"
