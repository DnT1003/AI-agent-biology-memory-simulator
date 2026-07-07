"""
FileReadTool – read files from the filesystem.

Port of: src/tools/FileReadTool/FileReadTool.ts
"""
from __future__ import annotations
import os
from typing import Any
from hare.tools_impl.FileReadTool.prompt import MAX_LINES_TO_READ, FILE_UNCHANGED_STUB

TOOL_NAME = "Read"
FILE_READ_TOOL_NAME = TOOL_NAME
_read_file_state: dict[str, float] = {}

def input_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Absolute file path"},
            "offset": {"type": "number", "description": "Line offset (1-based)"},
            "limit": {"type": "number", "description": "Max lines to read"},
        },
        "required": ["file_path"],
    }

def _format_lines(lines: list[str], start: int = 1) -> str:
    result: list[str] = []
    for i, line in enumerate(lines, start=start):
        result.append(f"{i:6d}|{line}")
    return "\n".join(result)

async def call(
    file_path: str,
    offset: int | None = None,
    limit: int | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    if not os.path.isabs(file_path):
        file_path = os.path.join(os.getcwd(), file_path)
    if not os.path.exists(file_path):
        return {"error": f"File not found: {file_path}"}
    if os.path.isdir(file_path):
        return {"error": f"Path is a directory: {file_path}. Use ls via Bash."}
    try:
        mtime = os.path.getmtime(file_path)
        if file_path in _read_file_state and _read_file_state[file_path] == mtime:
            return {"data": FILE_UNCHANGED_STUB}
        _read_file_state[file_path] = mtime
        ext = os.path.splitext(file_path)[1].lower()
        if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"):
            return {"data": f"[Image file: {file_path}]", "type": "image"}
        if ext == ".ipynb":
            return await _read_notebook(file_path)
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
        start = max(1, offset or 1)
        end_limit = limit or MAX_LINES_TO_READ
        selected = all_lines[start - 1 : start - 1 + end_limit]
        formatted = _format_lines(selected, start)
        result: dict[str, Any] = {"data": formatted}
        if len(all_lines) > start - 1 + end_limit:
            result["truncated"] = True
            result["totalLines"] = len(all_lines)
        return result
    except Exception as e:
        return {"error": str(e)}

async def _read_notebook(path: str) -> dict[str, Any]:
    import json
    with open(path, "r", encoding="utf-8") as f:
        nb = json.load(f)
    cells = nb.get("cells", [])
    parts: list[str] = []
    for i, cell in enumerate(cells):
        ctype = cell.get("cell_type", "code")
        source = "".join(cell.get("source", []))
        parts.append(f"--- Cell {i} ({ctype}) ---\n{source}")
    return {"data": "\n\n".join(parts)}
