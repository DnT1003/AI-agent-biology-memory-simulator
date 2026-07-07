"""Format LSP responses for model consumption. Port of: src/tools/LSPTool/formatters.ts"""

from __future__ import annotations

from typing import Any


def format_lsp_result(command: str, raw: dict[str, Any]) -> str:
    return f"{command}: {raw!r}"
