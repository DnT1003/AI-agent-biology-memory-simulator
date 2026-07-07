"""Port of: src/tools/shared/gitOperationTracking.ts"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

@dataclass
class GitOperation:
    command: str
    timestamp: float = 0.0
    exit_code: int = 0

class GitOperationTracker:
    def __init__(self) -> None:
        self._ops: list[GitOperation] = []
    def record(self, command: str, exit_code: int = 0) -> None:
        import time
        self._ops.append(GitOperation(command=command, timestamp=time.time(), exit_code=exit_code))
    def get_recent(self, limit: int = 20) -> list[GitOperation]:
        return self._ops[-limit:]
    def clear(self) -> None:
        self._ops.clear()
