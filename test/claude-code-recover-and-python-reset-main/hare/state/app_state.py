"""Port of: src/state/AppState.tsx + AppStateStore.ts"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Optional

@dataclass
class AppState:
    messages: list[dict[str, Any]] = field(default_factory=list)
    model: str = ""
    permission_mode: str = "default"
    session_id: str = ""
    project_dir: str = ""
    is_processing: bool = False
    is_plan_mode: bool = False
    agent_id: str = ""
    tools: list[dict[str, Any]] = field(default_factory=list)
    token_usage: dict[str, int] = field(default_factory=dict)

_global_state: Optional[AppState] = None

def get_app_state() -> AppState:
    global _global_state
    if _global_state is None:
        _global_state = AppState()
    return _global_state

def set_app_state(state: AppState) -> None:
    global _global_state
    _global_state = state
