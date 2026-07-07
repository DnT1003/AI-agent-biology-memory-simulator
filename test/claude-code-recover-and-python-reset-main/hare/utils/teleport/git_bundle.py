"""
Git bundle creation for teleport.

Port of: src/utils/teleport/gitBundle.ts
"""

from __future__ import annotations

import asyncio
from typing import Any


async def create_git_bundle(cwd: str, output_path: str) -> bool:
    """Create a git bundle file. Stub."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "bundle", "create", output_path, "--all",
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        return proc.returncode == 0
    except Exception:
        return False
