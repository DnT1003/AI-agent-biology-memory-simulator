"""
JWT utilities for bridge auth.

Port of: src/bridge/jwtUtils.ts
"""
from __future__ import annotations
import base64, json, time
from typing import Any


def decode_jwt_payload(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    padded = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(padded))
    except Exception:
        return {}


def decode_jwt_expiry(token: str) -> float | None:
    payload = decode_jwt_payload(token)
    exp = payload.get("exp")
    return float(exp) if exp else None


def create_token_refresh_scheduler(
    token: str,
    refresh_fn: Any,
    buffer_seconds: float = 60.0,
) -> dict[str, Any]:
    expiry = decode_jwt_expiry(token)
    if not expiry:
        return {"scheduled": False}
    delay = max(0, expiry - time.time() - buffer_seconds)
    return {"scheduled": True, "delay_seconds": delay}
