"""
Subscribe to compact warning suppression (non-React counterpart of the TS hook).

Port of: src/services/compact/compactWarningHook.ts
"""

from __future__ import annotations

from hare.services.compact.compact_warning_state import is_compact_warning_suppressed


def use_compact_warning_suppression() -> bool:
    """Return whether compact warnings are currently suppressed."""
    return is_compact_warning_suppressed()
