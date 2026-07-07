"""
Query configuration – immutable values snapshotted once at query() entry.

Port of: src/query/config.ts
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class QueryGates:
    streaming_tool_execution: bool = False
    emit_tool_use_summaries: bool = False
    is_ant: bool = False
    fast_mode_enabled: bool = True


@dataclass(frozen=True)
class QueryConfig:
    session_id: str = ""
    gates: QueryGates = QueryGates()


def build_query_config(session_id: str = "") -> QueryConfig:
    """Build config by snapshotting runtime gates."""
    return QueryConfig(
        session_id=session_id,
        gates=QueryGates(
            streaming_tool_execution=False,
            emit_tool_use_summaries=os.environ.get(
                "CLAUDE_CODE_EMIT_TOOL_USE_SUMMARIES", ""
            ).lower() in ("1", "true"),
            is_ant=os.environ.get("USER_TYPE") == "ant",
            fast_mode_enabled=os.environ.get(
                "CLAUDE_CODE_DISABLE_FAST_MODE", ""
            ).lower() not in ("1", "true"),
        ),
    )
