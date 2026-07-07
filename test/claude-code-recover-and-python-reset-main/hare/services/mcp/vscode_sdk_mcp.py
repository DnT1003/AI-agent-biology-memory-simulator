"""
VS Code extension SDK MCP bridge (stub).

Port of: src/services/mcp/vscodeSdkMcp.ts
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class VsCodeSdkMcpBridge:
    workspace_id: str = ""

    async def list_tools(self) -> list[dict[str, Any]]:
        return []
