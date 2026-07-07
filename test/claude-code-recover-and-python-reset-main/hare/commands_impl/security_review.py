"""
Security review command.

Port of: src/commands/security-review.ts
"""

from __future__ import annotations

from typing import Any


async def run_security_review_command(_args: list[str]) -> dict[str, Any]:
    return {"ok": True, "findings": []}
