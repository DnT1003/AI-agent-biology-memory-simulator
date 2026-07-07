"""
LSPTool – Language Server Protocol operations.

Port of: src/tools/LSPTool/LSPTool.ts
"""
from __future__ import annotations
from typing import Any

TOOL_NAME = "LSP"

OPERATIONS = ["definition", "references", "hover", "diagnostics", "rename",
              "incomingCalls", "outgoingCalls", "documentSymbols"]

def input_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "operation": {"type": "string", "enum": OPERATIONS},
            "filePath": {"type": "string"},
            "line": {"type": "number"},
            "character": {"type": "number"},
            "newName": {"type": "string"},
        },
        "required": ["operation", "filePath"],
    }

async def call(
    operation: str,
    filePath: str,
    line: int = 0,
    character: int = 0,
    newName: str = "",
    **kwargs: Any,
) -> dict[str, Any]:
    return {"data": f"LSP {operation} on {filePath}:{line}:{character} (stub)"}
