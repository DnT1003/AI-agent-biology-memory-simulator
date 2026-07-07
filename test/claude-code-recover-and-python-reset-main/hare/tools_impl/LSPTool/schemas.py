"""JSON schemas for LSPTool inputs. Port of: src/tools/LSPTool/schemas.ts"""

from __future__ import annotations

from typing import Any


def lsp_tool_input_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "LSP subcommand"},
            "path": {"type": "string"},
            "line": {"type": "integer"},
            "character": {"type": "integer"},
        },
        "required": ["command"],
    }
