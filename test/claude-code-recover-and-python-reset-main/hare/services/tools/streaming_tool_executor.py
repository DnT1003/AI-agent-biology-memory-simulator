"""
Streaming tool executor – manages concurrent tool execution.

Port of: src/services/tools/StreamingToolExecutor.ts
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolExecution:
    tool_use_id: str
    tool_name: str
    input_args: dict[str, Any]
    started_at: float = 0.0
    completed: bool = False
    result: Any = None
    error: str | None = None


class StreamingToolExecutor:
    """Manages streaming concurrent tool execution within a turn."""

    def __init__(self) -> None:
        self._executions: dict[str, ToolExecution] = {}
        self._pending: list[ToolExecution] = []

    def add_tool_use(
        self,
        tool_use_id: str,
        tool_name: str,
        input_args: dict[str, Any],
    ) -> None:
        """Register a new tool use block from the stream."""
        execution = ToolExecution(
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            input_args=input_args,
        )
        self._executions[tool_use_id] = execution
        self._pending.append(execution)

    def mark_tool_use_as_complete(
        self,
        tool_use_id: str,
        result: Any = None,
        error: str | None = None,
    ) -> None:
        """Mark a tool execution as complete."""
        execution = self._executions.get(tool_use_id)
        if execution:
            execution.completed = True
            execution.result = result
            execution.error = error

    @property
    def all_complete(self) -> bool:
        return all(e.completed for e in self._executions.values())

    @property
    def pending_count(self) -> int:
        return sum(1 for e in self._executions.values() if not e.completed)

    def get_results(self) -> list[dict[str, Any]]:
        """Get all tool results."""
        results = []
        for ex in self._executions.values():
            results.append({
                "tool_use_id": ex.tool_use_id,
                "tool_name": ex.tool_name,
                "completed": ex.completed,
                "result": ex.result,
                "error": ex.error,
            })
        return results
