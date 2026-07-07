"""Validate PowerShell invocation mode vs policy. Port of: src/tools/PowerShellTool/modeValidation.ts"""

from __future__ import annotations


def validate_powershell_mode(mode: str, allowed: set[str]) -> bool:
    return mode in allowed
