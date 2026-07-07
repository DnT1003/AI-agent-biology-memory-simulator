"""Path validation for PowerShell tool cwd / targets. Port of: src/tools/PowerShellTool/pathValidation.ts"""

from __future__ import annotations

from pathlib import Path


def is_path_within_workspace(candidate: Path, workspace_root: Path) -> bool:
    try:
        candidate.resolve().relative_to(workspace_root.resolve())
        return True
    except ValueError:
        return False
