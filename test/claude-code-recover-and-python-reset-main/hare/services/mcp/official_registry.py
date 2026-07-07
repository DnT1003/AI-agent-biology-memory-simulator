"""
Official Anthropic MCP registry URL set (cached).

Port of: src/services/mcp/officialRegistry.ts
"""

from __future__ import annotations

import asyncio
import json
import os
import urllib.request
from typing import Optional
from urllib.parse import urlparse, urlunparse

_official_urls: Optional[set[str]] = None


def _normalize_url(url: str) -> str | None:
    try:
        u = urlparse(url)
        stripped = urlunparse((u.scheme, u.netloc, u.path, "", "", ""))
        return stripped.rstrip("/")
    except Exception:
        return None


def _fetch_registry_sync() -> set[str]:
    urls: set[str] = set()
    req = urllib.request.Request(
        "https://api.anthropic.com/mcp-registry/v0/servers?version=latest&visibility=commercial",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        data = json.loads(resp.read().decode())
    for entry in data.get("servers", []):
        server = entry.get("server") or {}
        for remote in server.get("remotes") or []:
            u = remote.get("url")
            if isinstance(u, str):
                n = _normalize_url(u)
                if n:
                    urls.add(n)
    return urls


async def prefetch_official_mcp_urls() -> None:
    global _official_urls
    if os.environ.get("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"):
        return
    try:
        _official_urls = await asyncio.to_thread(_fetch_registry_sync)
    except Exception:
        pass


def is_official_mcp_url(normalized_url: str) -> bool:
    if _official_urls is None:
        return False
    return normalized_url in _official_urls


def reset_official_mcp_urls_for_testing() -> None:
    global _official_urls
    _official_urls = None
