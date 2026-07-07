"""Port of: src/commands/diff/. Show git diff."""
from typing import Any
import asyncio
async def call(args: list[str], context: Any) -> dict[str, Any]:
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "diff", "--stat",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        return {"type": "text", "value": stdout.decode(errors="replace") or "(no changes)"}
    except Exception as e:
        return {"type": "text", "value": f"Error: {e}"}
