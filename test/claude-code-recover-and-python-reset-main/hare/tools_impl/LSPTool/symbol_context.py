"""Resolve symbol context for LSP tool queries. Port of: src/tools/LSPTool/symbolContext.ts"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SymbolContext:
    uri: str
    line: int
    character: int
    name: str = ""


async def build_symbol_context(_uri: str, _line: int, _character: int) -> SymbolContext | None:
    return None
