"""
Bridge pointer – manages pointer files for worktree coordination.

Port of: src/bridge/bridgePointer.ts
"""
from __future__ import annotations
import json, os, time

BRIDGE_POINTER_TTL_MS = 300_000


def read_bridge_pointer(path: str) -> dict | None:
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if time.time() * 1000 - data.get("timestamp", 0) > BRIDGE_POINTER_TTL_MS:
            return None
        return data
    except (OSError, json.JSONDecodeError):
        return None


def write_bridge_pointer(path: str, data: dict) -> None:
    data["timestamp"] = int(time.time() * 1000)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def clear_bridge_pointer(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
