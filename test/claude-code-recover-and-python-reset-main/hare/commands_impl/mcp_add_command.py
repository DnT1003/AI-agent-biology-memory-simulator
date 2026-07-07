"""
MCP add-server command helpers.

Port of: src/commands/mcp/addCommand.ts
"""

from __future__ import annotations

from typing import Any


def parse_mcp_add_args(argv: list[str]) -> dict[str, Any]:
    return {"raw": argv}
