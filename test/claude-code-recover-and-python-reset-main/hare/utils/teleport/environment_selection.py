"""Resolve selected Teleport environment from settings.

Port of: src/utils/teleport/environmentSelection.ts
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass
class EnvironmentResource:
    environment_id: str
    kind: str
    name: str = ""


async def fetch_environments() -> list[EnvironmentResource]:
    """Stub: wire to Sessions API."""
    return []


SettingSource = Literal[
    "userSettings",
    "projectSettings",
    "localSettings",
    "policySettings",
    "managedSettings",
    "flagSettings",
]


@dataclass
class EnvironmentSelectionInfo:
    available_environments: list[EnvironmentResource]
    selected_environment: EnvironmentResource | None
    selected_environment_source: SettingSource | None


def _get_settings_deprecated() -> dict[str, Any]:
    return {}


def _get_settings_for_source(_source: SettingSource) -> dict[str, Any] | None:
    return None


async def get_environment_selection_info() -> EnvironmentSelectionInfo:
    environments = await fetch_environments()
    if not environments:
        return EnvironmentSelectionInfo([], None, None)
    merged = _get_settings_deprecated()
    default_id = (merged.get("remote") or {}).get("defaultEnvironmentId")
    selected = next((e for e in environments if e.kind != "bridge"), environments[0])
    source: SettingSource | None = None
    if default_id:
        match = next((e for e in environments if e.environment_id == default_id), None)
        if match:
            selected = match
    return EnvironmentSelectionInfo(environments, selected, source)
