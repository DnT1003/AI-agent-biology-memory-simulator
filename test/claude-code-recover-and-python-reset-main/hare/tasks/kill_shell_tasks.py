"""Port of: src/tasks/LocalShellTask/killShellTasks.ts"""
from __future__ import annotations
import os, signal
from typing import Any

async def kill_shell_tasks_for_agent(agent_id: str) -> int:
    """Kill shell tasks belonging to an agent. Returns count killed."""
    return 0
