"""Port of: src/utils/hooks/execAgentHook.ts"""
from __future__ import annotations
import asyncio, os
from typing import Any

async def exec_hook(command: str, *, cwd: str = "", timeout: float = 30.0) -> dict[str, Any]:
    try:
        proc = await asyncio.create_subprocess_shell(
            command, cwd=cwd or None,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return {
            "success": proc.returncode == 0,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "exit_code": proc.returncode or 0,
        }
    except asyncio.TimeoutError:
        return {"success": False, "error": "Hook timed out", "exit_code": 124}
    except Exception as e:
        return {"success": False, "error": str(e), "exit_code": 1}
