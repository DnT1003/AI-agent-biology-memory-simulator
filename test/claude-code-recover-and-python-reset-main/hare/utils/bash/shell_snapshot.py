"""Port of: src/utils/bash/ShellSnapshot.ts"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

@dataclass
class ShellSnapshot:
    cwd: str = ""
    env: dict[str, str] = field(default_factory=dict)
    pid: int = 0
    running: bool = False
