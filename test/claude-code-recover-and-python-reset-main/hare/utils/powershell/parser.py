"""
PowerShell AST parsing via pwsh — stub returning minimal structures.

Port of: src/utils/powershell/parser.ts
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

COMMON_ALIASES: dict[str, str] = {
    "ls": "Get-ChildItem",
    "dir": "Get-ChildItem",
    "cd": "Set-Location",
    "pwd": "Get-Location",
}


@dataclass
class ParsedCommandElement:
    name: str
    args: list[str]
    name_type: Literal["cmdlet", "application", "unknown"] = "unknown"
    element_types: list[str] | None = None


async def parse_powershell_command(_script: str) -> list[ParsedCommandElement]:
    """Invoke PowerShell AST export (stub)."""
    return []
