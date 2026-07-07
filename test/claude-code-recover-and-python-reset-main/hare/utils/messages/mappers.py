"""SDK message ↔ internal message mappers. Port of: src/utils/messages/mappers.ts"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def to_internal_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map SDK stream messages to internal Message shape (stub)."""
    out: list[dict[str, Any]] = []
    for m in messages:
        t = m.get("type")
        if t == "assistant":
            out.append(
                {
                    "type": "assistant",
                    "message": m.get("message"),
                    "uuid": m.get("uuid"),
                    "requestId": None,
                    "timestamp": __import__("datetime").datetime.utcnow().isoformat() + "Z",
                }
            )
        elif t == "user":
            out.append(
                {
                    "type": "user",
                    "message": m.get("message"),
                    "uuid": m.get("uuid"),
                    "timestamp": m.get("timestamp"),
                    "isMeta": m.get("isSynthetic"),
                }
            )
    return out


@dataclass
class CompactMetadata:
    """Placeholder for compact boundary metadata."""

    pass


def to_sdk_compact_metadata(meta: CompactMetadata) -> dict[str, Any]:
    return {}
