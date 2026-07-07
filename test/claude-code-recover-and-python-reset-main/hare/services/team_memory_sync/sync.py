"""
Team memory sync – synchronize CLAUDE.md across team members.

Port of: src/services/teamMemorySync/index.ts
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TeamMemorySyncService:
    team_dir: str = ""
    memory_file: str = "CLAUDE.md"
    _watchers: list[Any] = field(default_factory=list)

    async def start(self) -> None:
        """Start watching for team memory changes."""
        pass

    async def stop(self) -> None:
        """Stop watching."""
        for w in self._watchers:
            pass
        self._watchers.clear()

    async def broadcast_update(self, content: str) -> None:
        """Broadcast a memory update to team members."""
        memory_path = os.path.join(self.team_dir, self.memory_file)
        try:
            with open(memory_path, "w", encoding="utf-8") as f:
                f.write(content)
        except OSError:
            pass

    async def read_shared_memory(self) -> str:
        """Read the shared team memory file."""
        memory_path = os.path.join(self.team_dir, self.memory_file)
        try:
            with open(memory_path, "r", encoding="utf-8") as f:
                return f.read()
        except OSError:
            return ""


async def sync_team_memory(team_dir: str) -> None:
    """One-shot sync of team memory. Stub."""
    pass
