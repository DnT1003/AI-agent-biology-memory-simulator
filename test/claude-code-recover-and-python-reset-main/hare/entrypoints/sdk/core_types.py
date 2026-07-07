"""Port of: src/entrypoints/sdk/coreTypes.ts"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

@dataclass
class CoreConfig:
    model: str = ""
    max_turns: int = 100
    system_prompt: str = ""
    tools: list[str] = field(default_factory=list)
    permission_mode: str = "default"

@dataclass
class CoreResult:
    messages: list[dict[str, Any]] = field(default_factory=list)
    stop_reason: str = ""
    usage: dict[str, int] = field(default_factory=dict)
