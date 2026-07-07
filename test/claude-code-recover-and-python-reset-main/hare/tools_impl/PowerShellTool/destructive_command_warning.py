"""Warn on destructive PowerShell patterns. Port of: src/tools/PowerShellTool/destructiveCommandWarning.ts"""

from __future__ import annotations

import re

_DESTRUCTIVE = re.compile(
    r"\b(Remove-Item\s+-Recurse|Format-Volume|Clear-Disk|Stop-Computer|Restart-Computer)\b",
    re.IGNORECASE,
)


def is_potentially_destructive_powershell(command: str) -> bool:
    return bool(_DESTRUCTIVE.search(command))
