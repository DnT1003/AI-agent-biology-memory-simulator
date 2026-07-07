"""HTTP hook execution (requests stub).

Port of: src/utils/hooks/execHttpHook.ts
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class HttpHookResult:
    status_code: int
    body: str
    headers: dict[str, str]


async def exec_http_hook(
    url: str,
    *,
    method: str = "POST",
    headers: dict[str, str] | None = None,
    body: bytes | str | None = None,
    timeout_sec: float = 30.0,
) -> HttpHookResult:
    """Execute HTTP hook; stub until ``httpx`` / ``aiohttp`` wired."""
    del url, method, headers, body, timeout_sec
    return HttpHookResult(status_code=501, body="", headers={})
