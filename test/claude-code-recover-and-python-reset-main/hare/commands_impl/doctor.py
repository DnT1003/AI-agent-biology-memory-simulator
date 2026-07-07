"""Port of: src/commands/doctor/. Diagnose issues."""
from typing import Any
import sys, os
async def call(args: list[str], context: Any) -> dict[str, Any]:
    lines = [
        f"Python: {sys.version}",
        f"Platform: {sys.platform}",
        f"CWD: {os.getcwd()}",
        f"HOME: {os.path.expanduser('~')}",
    ]
    return {"type": "text", "value": "Doctor report:\n" + "\n".join(lines)}
