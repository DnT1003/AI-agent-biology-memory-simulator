"""Port of: src/entrypoints/sdk/controlSchemas.ts"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Literal

@dataclass
class ControlMessage:
    type: str = ""
    action: str = ""
    payload: dict[str, Any] | None = None
