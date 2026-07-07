"""
CLI config command – manage configuration.

Port of: src/entrypoints/cli/configCommand.ts
"""

from __future__ import annotations

import json
import os
from typing import Any


def get_config_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".claude", "config.json")


async def run_config_get(key: str) -> Any:
    """Get a config value."""
    config = _load_config()
    parts = key.split(".")
    current: Any = config
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


async def run_config_set(key: str, value: str) -> None:
    """Set a config value."""
    config = _load_config()
    parts = key.split(".")
    current = config
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            current[part] = {}
        current = current[part]
    try:
        current[parts[-1]] = json.loads(value)
    except json.JSONDecodeError:
        current[parts[-1]] = value
    _save_config(config)


def _load_config() -> dict[str, Any]:
    path = get_config_path()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_config(config: dict[str, Any]) -> None:
    path = get_config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
