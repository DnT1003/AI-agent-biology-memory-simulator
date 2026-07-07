"""Security classification for PowerShell commands. Port of: src/tools/PowerShellTool/powershellSecurity.ts"""

from __future__ import annotations


def classify_powershell_security(command: str) -> str:
    if "Invoke-Expression" in command or "iex" in command.lower():
        return "high"
    return "normal"
