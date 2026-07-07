"""
Harbor channel plugin allowlist (GrowthBook-backed).

Port of: src/services/mcp/channelAllowlist.ts
"""

from __future__ import annotations

from dataclasses import dataclass

from hare.services.analytics.growthbook import get_feature_value_cached_may_be_stale


@dataclass(frozen=True)
class ChannelAllowlistEntry:
    marketplace: str
    plugin: str


def _parse_plugin_identifier(plugin_source: str) -> tuple[str, str | None]:
    """Minimal `plugin:name@marketplace` parse for allowlist checks."""
    if "@" not in plugin_source or ":" not in plugin_source:
        return plugin_source, None
    try:
        left, marketplace = plugin_source.rsplit("@", 1)
        _, name = left.split(":", 1)
        return name, marketplace
    except ValueError:
        return plugin_source, None


def get_channel_allowlist() -> list[ChannelAllowlistEntry]:
    raw = get_feature_value_cached_may_be_stale("tengu_harbor_ledger", [])
    if not isinstance(raw, list):
        return []
    out: list[ChannelAllowlistEntry] = []
    for item in raw:
        if isinstance(item, dict):
            m = item.get("marketplace")
            p = item.get("plugin")
            if isinstance(m, str) and isinstance(p, str):
                out.append(ChannelAllowlistEntry(marketplace=m, plugin=p))
    return out


def is_channels_enabled() -> bool:
    return bool(get_feature_value_cached_may_be_stale("tengu_harbor", False))


def is_channel_allowlisted(plugin_source: str | None) -> bool:
    if not plugin_source:
        return False
    name, marketplace = _parse_plugin_identifier(plugin_source)
    if not marketplace:
        return False
    return any(e.plugin == name and e.marketplace == marketplace for e in get_channel_allowlist())
