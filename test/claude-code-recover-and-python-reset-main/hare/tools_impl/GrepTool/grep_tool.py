"""
GrepTool – ripgrep-based code search.

Port of: src/tools/GrepTool/GrepTool.ts
"""
from __future__ import annotations
import asyncio, os, json
from typing import Any

TOOL_NAME = "Grep"
GREP_TOOL_NAME = TOOL_NAME

def input_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Regex pattern"},
            "path": {"type": "string", "description": "Search directory"},
            "glob": {"type": "string", "description": "File glob filter"},
            "type": {"type": "string", "description": "File type filter"},
            "output_mode": {"type": "string", "enum": ["content", "files_with_matches", "count"]},
            "head_limit": {"type": "number"},
            "multiline": {"type": "boolean"},
        },
        "required": ["pattern"],
    }

async def call(
    pattern: str,
    path: str | None = None,
    output_mode: str = "files_with_matches",
    head_limit: int | None = None,
    multiline: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    base = path or os.getcwd()
    args = ["rg", "--json"]
    if output_mode == "files_with_matches":
        args.append("-l")
    elif output_mode == "count":
        args.append("-c")
    if multiline:
        args.extend(["-U", "--multiline-dotall"])
    if kwargs.get("glob"):
        args.extend(["--glob", kwargs["glob"]])
    if kwargs.get("type"):
        args.extend(["--type", kwargs["type"]])
    args.extend(["--", pattern, base])
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        output = stdout.decode("utf-8", errors="replace")
        lines = output.strip().split("\n") if output.strip() else []
        if head_limit and len(lines) > head_limit:
            lines = lines[:head_limit]
        return {"output": "\n".join(lines), "matchCount": len(lines)}
    except FileNotFoundError:
        return {"error": "ripgrep (rg) not found in PATH"}
    except Exception as e:
        return {"error": str(e)}
