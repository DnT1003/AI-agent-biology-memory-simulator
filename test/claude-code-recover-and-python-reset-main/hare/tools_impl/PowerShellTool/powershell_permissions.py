"""PowerShell permission / capability checks. Port of: src/tools/PowerShellTool/powershellPermissions.ts"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PowershellPermissionContext:
    allow_network: bool = False
    allow_git_write: bool = False


def needs_extra_permission(_command: str, _ctx: PowershellPermissionContext) -> bool:
    return False
