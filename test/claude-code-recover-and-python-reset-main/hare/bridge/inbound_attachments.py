"""Port of: src/bridge/inboundAttachments.ts"""
from __future__ import annotations
import os
from typing import Any

def extract_inbound_attachments(msg: dict[str, Any]) -> list[dict[str, Any]]:
    return msg.get("attachments", [])

def resolve_inbound_attachments(attachments: list[dict[str, Any]], cwd: str) -> list[dict[str, Any]]:
    resolved: list[dict[str, Any]] = []
    for a in attachments:
        path = a.get("path", "")
        full = path if os.path.isabs(path) else os.path.join(cwd, path)
        resolved.append({**a, "resolved_path": full, "exists": os.path.exists(full)})
    return resolved
