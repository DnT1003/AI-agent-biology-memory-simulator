"""
Cron expression parsing and formatting.

Port of: src/utils/cron.ts
"""

from __future__ import annotations

import re
from typing import Any


def parse_cron_expression(expr: str) -> dict[str, Any] | None:
    """Parse a 5-field cron expression. Returns parsed fields or None if invalid."""
    parts = expr.strip().split()
    if len(parts) != 5:
        return None
    return {
        "minute": parts[0],
        "hour": parts[1],
        "day_of_month": parts[2],
        "month": parts[3],
        "day_of_week": parts[4],
    }


def cron_to_human(expr: str) -> str:
    """Convert a cron expression to a human-readable description."""
    parsed = parse_cron_expression(expr)
    if not parsed:
        return expr

    m, h, dom, mon, dow = (
        parsed["minute"], parsed["hour"],
        parsed["day_of_month"], parsed["month"], parsed["day_of_week"],
    )

    if m.startswith("*/"):
        return f"every {m[2:]} minutes"
    if h.startswith("*/"):
        return f"every {h[2:]} hours"
    if m == "0" and h == "*":
        return "every hour"
    if dom == "*" and mon == "*" and dow == "*":
        return f"daily at {h}:{m.zfill(2)}"
    return expr


def next_cron_run_ms(expr: str, now_ms: float) -> float | None:
    """Calculate next run time in ms. Simplified stub."""
    parsed = parse_cron_expression(expr)
    if not parsed:
        return None
    return now_ms + 60_000
