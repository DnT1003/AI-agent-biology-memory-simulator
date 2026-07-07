"""Load permissions from settings files. Port of permissionsLoader.ts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_permissions_from_path(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        perms = data.get("permissions")
        return perms if isinstance(perms, list) else []
    except (json.JSONDecodeError, OSError):
        return []
