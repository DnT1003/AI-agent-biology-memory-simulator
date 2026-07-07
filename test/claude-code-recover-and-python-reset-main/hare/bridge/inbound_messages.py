"""Port of: src/bridge/inboundMessages.ts"""
from __future__ import annotations
from typing import Any

def extract_inbound_message_fields(msg: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": msg.get("content", msg.get("message", "")),
        "type": msg.get("type", "user"),
    }

def normalize_image_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return blocks
