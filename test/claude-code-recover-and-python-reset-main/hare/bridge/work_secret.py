"""
Work secret – decode base64url JSON secret from bridge poll.

Port of: src/bridge/workSecret.ts
"""
from __future__ import annotations
import base64, json
from typing import Any
from hare.bridge.types import WorkSecret


def decode_work_secret(encoded: str) -> WorkSecret:
    padded = encoded + "=" * (-len(encoded) % 4)
    raw = base64.urlsafe_b64decode(padded)
    data = json.loads(raw)
    return WorkSecret(
        session_id=data.get("session_id", ""),
        access_token=data.get("access_token", ""),
        sdk_url=data.get("sdk_url", ""),
        bridge_id=data.get("bridge_id", ""),
    )


def build_sdk_url(secret: WorkSecret) -> str:
    return secret.sdk_url or ""


def same_session_id(a: str, b: str) -> bool:
    return a.replace("cse_", "").replace("session_", "") == b.replace("cse_", "").replace("session_", "")
