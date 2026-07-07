"""
Misc helpers shared by hook runners.

Port of: src/utils/hooks/hookHelpers.ts
"""

from __future__ import annotations

import json
from typing import Any


def normalize_hook_json_output(raw: str) -> dict[str, Any] | None:
    """Parse first JSON object line from hook stdout."""
    for line in raw.splitlines():
        t = line.strip()
        if t.startswith("{"):
            try:
                return json.loads(t)
            except json.JSONDecodeError:
                continue
    return None


def merge_hook_decisions(
    base: dict[str, Any],
    override: dict[str, Any],
) -> dict[str, Any]:
    out = dict(base)
    out.update(override)
    return out
