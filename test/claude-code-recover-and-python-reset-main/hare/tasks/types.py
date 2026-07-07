"""Port of: src/tasks/types.ts"""
from __future__ import annotations
from typing import Literal
TaskType = Literal["shell", "agent", "dream"]
TaskState = Literal["pending", "running", "completed", "failed", "cancelled"]
