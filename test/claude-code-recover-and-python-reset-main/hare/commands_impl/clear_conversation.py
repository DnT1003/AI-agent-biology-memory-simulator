"""
Clear conversation transcript (subcommand).

Port of: src/commands/clear/conversation.ts
"""

from __future__ import annotations

from typing import Any


async def clear_conversation() -> dict[str, Any]:
    return {"cleared": True}
