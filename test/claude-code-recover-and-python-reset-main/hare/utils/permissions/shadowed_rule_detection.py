"""Detect shadowed allow/deny rules. Port of shadowedRuleDetection.ts."""

from __future__ import annotations

from typing import Any


def find_shadowed_rules(rules: list[dict[str, Any]]) -> list[tuple[int, int]]:
    """Return pairs of indices where an earlier rule shadows a later one."""
    shadows: list[tuple[int, int]] = []
    for i, a in enumerate(rules):
        for j in range(i + 1, len(rules)):
            b = rules[j]
            if a.get("pattern") == b.get("pattern") and a.get("type") != b.get("type"):
                shadows.append((i, j))
    return shadows
