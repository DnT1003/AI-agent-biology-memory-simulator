"""
Pure MCP server/tool name normalization.

Port of: src/services/mcp/normalization.ts
"""

from __future__ import annotations

CLAUDEAI_SERVER_PREFIX = "claude.ai "


def normalize_name_for_mcp(name: str) -> str:
    """
    Normalize server names for API pattern ^[a-zA-Z0-9_-]{1,64}$.
    For claude.ai servers, collapse underscores and strip leading/trailing underscores.
    """
    import re

    normalized = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
    if name.startswith(CLAUDEAI_SERVER_PREFIX):
        normalized = re.sub(r"_+", "_", normalized)
        normalized = re.sub(r"^_|_$", "", normalized)
    return normalized
