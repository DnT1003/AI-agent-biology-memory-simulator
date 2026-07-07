"""
Session history – paginated event retrieval from the sessions API.

Port of: src/assistant/sessionHistory.ts
"""

from __future__ import annotations

import json
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import Any

HISTORY_PAGE_SIZE = 100


@dataclass
class HistoryPage:
    events: list[dict[str, Any]] = field(default_factory=list)
    first_id: str | None = None
    has_more: bool = False


@dataclass
class HistoryAuthCtx:
    base_url: str = ""
    headers: dict[str, str] = field(default_factory=dict)


async def create_history_auth_ctx(session_id: str) -> HistoryAuthCtx:
    """Prepare auth + headers + base URL once, reuse across pages."""
    base_api_url = "https://api.claude.ai"
    return HistoryAuthCtx(
        base_url=f"{base_api_url}/v1/sessions/{session_id}/events",
        headers={
            "Content-Type": "application/json",
            "anthropic-beta": "ccr-byoc-2025-07-29",
        },
    )


def _fetch_page(
    ctx: HistoryAuthCtx,
    params: dict[str, Any],
) -> HistoryPage | None:
    """Fetch a single page of events."""
    try:
        query = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{ctx.base_url}?{query}" if query else ctx.base_url
        req = urllib.request.Request(url, headers=ctx.headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            return HistoryPage(
                events=data.get("data", []),
                first_id=data.get("first_id"),
                has_more=data.get("has_more", False),
            )
    except Exception:
        return None


async def fetch_latest_events(
    ctx: HistoryAuthCtx,
    limit: int = HISTORY_PAGE_SIZE,
) -> HistoryPage | None:
    """Newest page: last `limit` events, chronological."""
    return _fetch_page(ctx, {"limit": limit, "anchor_to_latest": "true"})


async def fetch_older_events(
    ctx: HistoryAuthCtx,
    before_id: str,
    limit: int = HISTORY_PAGE_SIZE,
) -> HistoryPage | None:
    """Older page: events immediately before `before_id` cursor."""
    return _fetch_page(ctx, {"limit": limit, "before_id": before_id})
