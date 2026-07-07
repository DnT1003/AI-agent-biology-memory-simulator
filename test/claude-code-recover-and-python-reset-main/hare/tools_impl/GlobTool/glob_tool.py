"""
GlobTool – fast file pattern matching.

Port of: src/tools/GlobTool/GlobTool.ts
"""
from __future__ import annotations
import glob as _glob, os
from typing import Any

TOOL_NAME = "Glob"
GLOB_TOOL_NAME = TOOL_NAME
MAX_RESULTS = 500

def input_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Glob pattern"},
            "path": {"type": "string", "description": "Base directory"},
        },
        "required": ["pattern"],
    }

async def call(pattern: str, path: str | None = None, **kwargs: Any) -> dict[str, Any]:
    base = path or os.getcwd()
    full_pattern = os.path.join(base, pattern)
    matches = sorted(_glob.glob(full_pattern, recursive=True), key=os.path.getmtime, reverse=True)
    truncated = len(matches) > MAX_RESULTS
    matches = matches[:MAX_RESULTS]
    relative = [os.path.relpath(m, base).replace("\\", "/") for m in matches if os.path.isfile(m)]
    return {"files": relative, "truncated": truncated}
