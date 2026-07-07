"""
FileWriteTool – write files to the filesystem.

Port of: src/tools/FileWriteTool/FileWriteTool.ts
"""
from __future__ import annotations
import os
from typing import Any

TOOL_NAME = "Write"
FILE_WRITE_TOOL_NAME = TOOL_NAME

def input_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "File path to write"},
            "content": {"type": "string", "description": "File content"},
        },
        "required": ["file_path", "content"],
    }

async def call(file_path: str, content: str, **kwargs: Any) -> dict[str, Any]:
    if not os.path.isabs(file_path):
        file_path = os.path.join(os.getcwd(), file_path)
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        existed = os.path.isfile(file_path)
        with open(file_path, "w", encoding="utf-8", newline="") as f:
            f.write(content)
        line_count = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
        return {
            "data": f"{'Updated' if existed else 'Created'} {file_path} ({line_count} lines)",
            "file_path": file_path,
            "created": not existed,
        }
    except Exception as e:
        return {"error": str(e)}
