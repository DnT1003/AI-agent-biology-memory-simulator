"""
FileEditTool – edit files with string replacement.

Port of: src/tools/FileEditTool/FileEditTool.ts
"""
from __future__ import annotations
import os
from typing import Any

TOOL_NAME = "Edit"
FILE_EDIT_TOOL_NAME = TOOL_NAME

def input_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "file_path": {"type": "string"},
            "old_string": {"type": "string", "description": "Text to find"},
            "new_string": {"type": "string", "description": "Replacement text"},
            "replace_all": {"type": "boolean", "description": "Replace all occurrences"},
        },
        "required": ["file_path", "old_string", "new_string"],
    }

async def call(
    file_path: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    if not os.path.isabs(file_path):
        file_path = os.path.join(os.getcwd(), file_path)
    if not os.path.isfile(file_path):
        return {"error": f"File not found: {file_path}"}
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        count = content.count(old_string)
        if count == 0:
            return {"error": f"old_string not found in {file_path}"}
        if count > 1 and not replace_all:
            return {"error": f"old_string found {count} times. Use replace_all=true or provide more context."}
        if replace_all:
            new_content = content.replace(old_string, new_string)
        else:
            new_content = content.replace(old_string, new_string, 1)
        with open(file_path, "w", encoding="utf-8", newline="") as f:
            f.write(new_content)
        replacements = count if replace_all else 1
        return {"data": f"Edited {file_path} ({replacements} replacement{'s' if replacements > 1 else ''})"}
    except Exception as e:
        return {"error": str(e)}
