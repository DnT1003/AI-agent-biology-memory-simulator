"""Delisted plugin detection and auto-uninstall. Port of pluginBlocklist.ts."""

from __future__ import annotations

from typing import Any

from hare.utils.debug import log_for_debugging
from hare.utils.errors import error_message


def detect_delisted_plugins(
    installed_plugins: dict[str, Any],
    marketplace: dict[str, Any],
    marketplace_name: str,
) -> list[str]:
    names = {p["name"] for p in marketplace.get("plugins", [])}
    suffix = f"@{marketplace_name}"
    delisted: list[str] = []
    for plugin_id in installed_plugins.get("plugins", {}).keys():
        if not str(plugin_id).endswith(suffix):
            continue
        plugin_name = str(plugin_id)[: -len(suffix)]
        if plugin_name not in names:
            delisted.append(str(plugin_id))
    return delisted


async def detect_and_uninstall_delisted_plugins() -> list[str]:
    """Stub orchestration — wire pluginOperations + marketplaceManager."""
    await _load_flagged_plugins_stub()
    log_for_debugging("detect_and_uninstall_delisted_plugins (stub)")
    return []


async def _load_flagged_plugins_stub() -> None:
    pass
