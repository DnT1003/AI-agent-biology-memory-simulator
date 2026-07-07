"""MCP instructions delta for conversation attachments — port of `mcpInstructionsDelta.ts`."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from hare.utils.env_utils import is_env_defined_falsy, is_env_truthy


def get_feature_value_cached_may_be_stale(_key: str, default: bool) -> bool:
    return default


def log_event(_name: str, _payload: dict[str, Any]) -> None:
    """Stub analytics."""


@dataclass
class McpInstructionsDelta:
    added_names: list[str] = field(default_factory=list)
    added_blocks: list[str] = field(default_factory=list)
    removed_names: list[str] = field(default_factory=list)


@dataclass
class ClientSideInstruction:
    server_name: str
    block: str


def is_mcp_instructions_delta_enabled() -> bool:
    raw = os.environ.get("CLAUDE_CODE_MCP_INSTR_DELTA")
    if is_env_truthy(raw):
        return True
    if is_env_defined_falsy(raw):
        return False
    return os.environ.get("USER_TYPE") == "ant" or get_feature_value_cached_may_be_stale("tengu_basalt_3kr", False)


def get_mcp_instructions_delta(
    mcp_clients: list[Any],
    messages: list[Any],
    client_side_instructions: list[ClientSideInstruction],
) -> McpInstructionsDelta | None:
    announced: set[str] = set()
    attachment_count = 0
    mid_count = 0
    for msg in messages:
        if getattr(msg, "type", None) != "attachment":
            continue
        attachment_count += 1
        att = getattr(msg, "attachment", None)
        if not att or getattr(att, "type", None) != "mcp_instructions_delta":
            continue
        mid_count += 1
        for n in getattr(att, "added_names", []) or []:
            announced.add(n)
        for n in getattr(att, "removed_names", []) or []:
            announced.discard(n)

    connected = [c for c in mcp_clients if getattr(c, "type", None) == "connected"]
    connected_names = {getattr(c, "name", "") for c in connected}

    blocks: dict[str, str] = {}
    for c in connected:
        name = getattr(c, "name", "")
        instr = getattr(c, "instructions", None)
        if instr:
            blocks[name] = f"## {name}\n{instr}"
    for ci in client_side_instructions:
        if ci.server_name not in connected_names:
            continue
        existing = blocks.get(ci.server_name)
        blocks[ci.server_name] = (
            f"{existing}\n\n{ci.block}" if existing else f"## {ci.server_name}\n{ci.block}"
        )

    added: list[tuple[str, str]] = []
    for name, block in blocks.items():
        if name not in announced:
            added.append((name, block))

    removed = [n for n in announced if n not in connected_names]

    if not added and not removed:
        return None

    log_event(
        "tengu_mcp_instructions_pool_change",
        {
            "addedCount": len(added),
            "removedCount": len(removed),
            "priorAnnouncedCount": len(announced),
            "clientSideCount": len(client_side_instructions),
            "messagesLength": len(messages),
            "attachmentCount": attachment_count,
            "midCount": mid_count,
        },
    )

    added.sort(key=lambda x: x[0])
    return McpInstructionsDelta(
        added_names=[a[0] for a in added],
        added_blocks=[a[1] for a in added],
        removed_names=sorted(removed),
    )
