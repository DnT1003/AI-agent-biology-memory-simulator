"""Port of: src/utils/settings/pluginOnlyPolicy.ts"""
from __future__ import annotations

def is_restricted_to_plugin_only(feature: str = "") -> bool:
    return False

def is_source_admin_trusted(source: str) -> bool:
    return source in ("built-in", "plugin", "policySettings")
