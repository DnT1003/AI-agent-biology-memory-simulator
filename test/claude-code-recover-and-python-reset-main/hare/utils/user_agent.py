"""User-Agent string for Claude Code (port of userAgent.ts)."""

from __future__ import annotations

_VERSION = "2.1.88"


def get_claude_code_user_agent() -> str:
    return f"claude-code/{_VERSION}"
