"""
OAuth loopback redirect port selection.

Port of: src/services/mcp/oauthPort.ts
"""

from __future__ import annotations

import os
import random
import socket
import sys


def _redirect_range() -> tuple[int, int]:
    if sys.platform == "win32":
        return 39152, 49151
    return 49152, 65535


REDIRECT_PORT_FALLBACK = 3118


def build_redirect_uri(port: int = REDIRECT_PORT_FALLBACK) -> str:
    return f"http://127.0.0.1:{port}/callback"


def _configured_port() -> int | None:
    raw = os.environ.get("MCP_OAUTH_CALLBACK_PORT", "")
    try:
        p = int(raw, 10)
        return p if p > 0 else None
    except ValueError:
        return None


def _port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


async def find_available_port() -> int:
    configured = _configured_port()
    if configured is not None:
        return configured
    min_p, max_p = _redirect_range()
    span = max_p - min_p + 1
    attempts = min(span, 100)
    for _ in range(attempts):
        port = min_p + random.randint(0, span - 1)
        if _port_available(port):
            return port
    if _port_available(REDIRECT_PORT_FALLBACK):
        return REDIRECT_PORT_FALLBACK
    raise RuntimeError("No available ports for OAuth redirect")
