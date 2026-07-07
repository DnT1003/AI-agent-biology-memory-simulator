"""
Claude.ai-hosted MCP integration helpers (stub).

Port of: src/services/mcp/claudeai.ts
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ClaudeAiMcpServerRef:
    name: str
    org_id: str = ""


async def connect_claude_ai_mcp_server(_ref: ClaudeAiMcpServerRef) -> None:
    return
