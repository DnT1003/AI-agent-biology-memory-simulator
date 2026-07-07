"""
Permission prompts relayed over MCP channel servers.

Port of: src/services/mcp/channelPermissions.ts
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Literal, TypeVar

from hare.services.analytics.growthbook import get_feature_value_cached_may_be_stale

T = TypeVar("T")  # used by filter_permission_relay_clients

PERMISSION_REPLY_RE = r"^\s*(y|yes|n|no)\s+([a-km-z]{5})\s*$"
ID_ALPHABET = "abcdefghijkmnopqrstuvwxyz"
ID_AVOID_SUBSTRINGS = (
    "fuck",
    "shit",
    "cunt",
    "cock",
    "dick",
    "twat",
    "piss",
    "crap",
    "bitch",
    "whore",
    "ass",
    "tit",
    "cum",
    "fag",
    "dyke",
    "nig",
    "kike",
    "rape",
    "nazi",
    "damn",
    "poo",
    "pee",
    "wank",
    "anus",
)


def is_channel_permission_relay_enabled() -> bool:
    return bool(get_feature_value_cached_may_be_stale("tengu_harbor_permissions", False))


@dataclass
class ChannelPermissionResponse:
    behavior: Literal["allow", "deny"]
    from_server: str


class ChannelPermissionCallbacks:
    def on_response(
        self, request_id: str, handler: Callable[[ChannelPermissionResponse], None]
    ) -> Callable[[], None]:
        raise NotImplementedError

    def resolve(self, request_id: str, behavior: Literal["allow", "deny"], from_server: str) -> bool:
        raise NotImplementedError


def _fnv1a32(data: str) -> int:
    h = 0x811C9DC5
    for ch in data:
        h ^= ord(ch)
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def _hash_to_id(input_str: str) -> str:
    h = _fnv1a32(input_str)
    s = ""
    for _ in range(5):
        s += ID_ALPHABET[h % 25]
        h //= 25
    return s


def short_request_id(tool_use_id: str) -> str:
    candidate = _hash_to_id(tool_use_id)
    for salt in range(10):
        if not any(bad in candidate for bad in ID_AVOID_SUBSTRINGS):
            return candidate
        candidate = _hash_to_id(f"{tool_use_id}:{salt}")
    return candidate


def truncate_for_preview(input_obj: Any) -> str:
    try:
        s = json.dumps(input_obj, default=str)
    except Exception:
        return "(unserializable)"
    return s if len(s) <= 200 else s[:200] + "…"


def filter_permission_relay_clients(
    clients: list[T],
    is_in_allowlist: Callable[[str], bool],
) -> list[T]:
    out: list[T] = []
    for c in clients:
        if getattr(c, "type", None) != "connected":
            continue
        name = getattr(c, "name", "")
        if not is_in_allowlist(str(name)):
            continue
        cap = getattr(c, "capabilities", None)
        exp = getattr(cap, "experimental", None) if cap else None
        if isinstance(exp, dict):
            if exp.get("claude/channel") is not None and exp.get("claude/channel/permission") is not None:
                out.append(c)
    return out


def create_channel_permission_callbacks() -> dict[str, Any]:
    pending: dict[str, Callable[[ChannelPermissionResponse], None]] = {}

    def on_response(request_id: str, handler: Callable[[ChannelPermissionResponse], None]) -> Callable[[], None]:
        key = request_id.lower()
        pending[key] = handler

        def unsub() -> None:
            pending.pop(key, None)

        return unsub

    def resolve(request_id: str, behavior: Literal["allow", "deny"], from_server: str) -> bool:
        key = request_id.lower()
        resolver = pending.pop(key, None)
        if not resolver:
            return False
        resolver(ChannelPermissionResponse(behavior=behavior, from_server=from_server))
        return True

    return {"on_response": on_response, "resolve": resolve}
