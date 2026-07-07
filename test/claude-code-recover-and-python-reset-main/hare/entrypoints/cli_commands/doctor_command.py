"""
CLI doctor command – diagnose installation issues.

Port of: src/entrypoints/cli/doctorCommand.ts
"""

from __future__ import annotations

import os
import sys
import shutil
from typing import Any


async def run_doctor_command() -> dict[str, Any]:
    """Run diagnostic checks."""
    checks: list[dict[str, Any]] = []

    checks.append({
        "name": "Python version",
        "status": "ok" if sys.version_info >= (3, 11) else "warn",
        "detail": sys.version,
    })

    git = shutil.which("git")
    checks.append({
        "name": "Git available",
        "status": "ok" if git else "error",
        "detail": git or "not found",
    })

    home_dir = os.path.expanduser("~")
    claude_dir = os.path.join(home_dir, ".claude")
    checks.append({
        "name": "Config directory",
        "status": "ok" if os.path.isdir(claude_dir) else "warn",
        "detail": claude_dir,
    })

    return {"checks": checks}
