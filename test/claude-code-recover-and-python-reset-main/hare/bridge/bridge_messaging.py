"""
Bridge messaging – ingress parsing, title extraction, result building.

Port of: src/bridge/bridgeMessaging.ts
"""
from __future__ import annotations
from typing import Any
import uuid


class BoundedUUIDSet:
    def __init__(self, max_size: int = 1000):
        self._max = max_size
        self._items: list[str] = []
        self._set: set[str] = set()

    def add(self, item: str) -> bool:
        if item in self._set:
            return False
        self._items.append(item)
        self._set.add(item)
        while len(self._items) > self._max:
            removed = self._items.pop(0)
            self._set.discard(removed)
        return True

    def __contains__(self, item: str) -> bool:
        return item in self._set


def handle_ingress_message(msg: dict[str, Any]) -> dict[str, Any] | None:
    msg_type = msg.get("type", "")
    if msg_type in ("user_message", "text"):
        return {"type": "user", "content": msg.get("content", msg.get("message", ""))}
    return None


def make_result_message(text: str) -> dict[str, Any]:
    return {"type": "result", "id": str(uuid.uuid4()), "content": text}


def extract_title(messages: list[dict[str, Any]]) -> str:
    for m in messages:
        content = m.get("content", "")
        if isinstance(content, str) and content.strip():
            title = content.strip()[:80]
            return title
    return "Untitled"
