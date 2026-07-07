"""
Marketplace reconciler — diff declared settings vs materialized JSON.

Port of: src/utils/plugins/reconciler.ts
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from hare.bootstrap.state import get_original_cwd
from hare.utils.debug import log_for_debugging
from hare.utils.errors import error_message


@dataclass
class MarketplaceDiff:
    missing: list[str] = field(default_factory=list)
    source_changed: list[dict[str, Any]] = field(default_factory=list)
    up_to_date: list[str] = field(default_factory=list)


def normalize_source(source: Any, project_root: str | None = None) -> Any:
    """Resolve relative paths; stub — extend with git canonicalization."""
    return source


def diff_marketplaces(
    declared: dict[str, Any],
    materialized: dict[str, Any],
    *,
    project_root: str | None = None,
) -> MarketplaceDiff:
    missing: list[str] = []
    source_changed: list[dict[str, Any]] = []
    up_to_date: list[str] = []

    for name, intent in declared.items():
        state = materialized.get(name)
        normalized_intent = normalize_source(intent.get("source"), project_root)
        if not state:
            missing.append(name)
            continue
        if intent.get("sourceIsFallback"):
            up_to_date.append(name)
            continue
        if normalized_intent != state.get("source"):
            source_changed.append(
                {
                    "name": name,
                    "declaredSource": normalized_intent,
                    "materializedSource": state.get("source"),
                }
            )
        else:
            up_to_date.append(name)

    return MarketplaceDiff(
        missing=missing, source_changed=source_changed, up_to_date=up_to_date
    )


async def reconcile_marketplaces(
    *,
    skip: Callable[[str, Any], bool] | None = None,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    """Bundle diff + install; stub — wire to marketplace I/O."""
    log_for_debugging(
        f"reconcile_marketplaces stub cwd={get_original_cwd()}",
    )
