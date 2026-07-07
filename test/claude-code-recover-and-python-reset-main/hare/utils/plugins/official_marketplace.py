"""
Official Anthropic plugins marketplace constants.

Port of: src/utils/plugins/officialMarketplace.ts
"""

from __future__ import annotations

from typing import Any

OFFICIAL_MARKETPLACE_SOURCE: dict[str, Any] = {
    "source": "github",
    "repo": "anthropics/claude-plugins-official",
}

OFFICIAL_MARKETPLACE_NAME = "claude-plugins-official"
