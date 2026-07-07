"""
PR comments command.

Port of: src/commands/pr_comments/index.ts
"""

from __future__ import annotations

from typing import Any


async def run_pr_comments_command(_args: list[str]) -> dict[str, Any]:
    return {"ok": True, "comments": []}
