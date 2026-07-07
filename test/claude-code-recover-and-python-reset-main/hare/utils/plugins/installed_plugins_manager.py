"""installed_plugins.json read/write and migrations. Port of installedPluginsManager.ts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hare.utils.env_utils import get_claude_config_home_dir


def _installed_path() -> Path:
    return Path(get_claude_config_home_dir()) / "installed_plugins.json"


def load_installed_plugins_v2() -> dict[str, Any]:
    """Return v2 structure or empty default."""
    p = _installed_path()
    if not p.is_file():
        return {"version": 2, "plugins": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"version": 2, "plugins": {}}
    except json.JSONDecodeError:
        return {"version": 2, "plugins": {}}


def load_installed_plugins_from_disk() -> dict[str, Any]:
    return load_installed_plugins_v2()


def save_installed_plugins_v2(_data: dict[str, Any]) -> None:
    """Stub persistence."""
    raise NotImplementedError
