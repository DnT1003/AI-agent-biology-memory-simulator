"""Port of: src/tasks/guards.ts"""
from __future__ import annotations
from hare.tasks.types import TaskState

def is_task_running(state: str) -> bool:
    return state in ("pending", "running")

def can_stop_task(state: str) -> bool:
    return state in ("pending", "running")

def is_task_done(state: str) -> bool:
    return state in ("completed", "failed", "cancelled")
