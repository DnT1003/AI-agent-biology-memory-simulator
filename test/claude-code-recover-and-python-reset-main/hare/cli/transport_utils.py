"""Choose WS/SSE/hybrid transport (port of src/cli/transports/transportUtils.ts)."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

from hare.cli.transports import Transport


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").lower() in ("1", "true", "yes")


def get_transport_for_url(
    url: str,
    headers: dict[str, str] | None = None,
    session_id: str | None = None,
    refresh_headers: Any | None = None,
) -> Transport:
    _ = (headers, session_id, refresh_headers)
    parsed = urlparse(url)
    if _env_truthy("CLAUDE_CODE_USE_CCR_V2"):
        from hare.cli.sse_transport import SSETransport

        return SSETransport(url)  # type: ignore[return-value]
    if parsed.scheme in ("ws", "wss"):
        if _env_truthy("CLAUDE_CODE_POST_FOR_SESSION_INGRESS_V2"):
            from hare.cli.hybrid_transport import HybridTransport

            return HybridTransport(url)
        from hare.cli.websocket_transport import WebSocketTransport

        return WebSocketTransport(url)
    raise ValueError(f"Unsupported protocol: {parsed.scheme}")
