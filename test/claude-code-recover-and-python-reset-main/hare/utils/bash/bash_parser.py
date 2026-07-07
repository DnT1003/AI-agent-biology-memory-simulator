"""
Pure parser facade compatible with tree-sitter-bash node shape.

Port of: src/utils/bash/bashParser.ts (subset: types, keywords, module API).

The TypeScript implementation contains a full lexer/parser; the Python build
uses a native/stub :func:`parse_source` hook when available.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


class _ParseAbortedType:
    __slots__ = ()


PARSE_ABORTED = _ParseAbortedType()


@dataclass
class TsNode:
    """AST node (UTF-8 byte offsets for start/end, matching tree-sitter)."""

    type: str
    text: str
    start_index: int
    end_index: int
    children: list[Any] = field(default_factory=list)


class ParserModule(Protocol):
    parse: Callable[[str, float | None], TsNode | None]


SHELL_KEYWORDS: frozenset[str] = frozenset(
    {
        "if",
        "then",
        "elif",
        "else",
        "fi",
        "while",
        "until",
        "for",
        "in",
        "do",
        "done",
        "case",
        "esac",
        "function",
        "select",
    }
)

_DECL_KEYWORDS: frozenset[str] = frozenset(
    {"export", "declare", "typeset", "readonly", "local"}
)

_MODULE: ParserModule | None = None
_PARSE_TIMEOUT_MS = 50.0


def _default_parse(_source: str, _timeout_ms: float | None = None) -> TsNode | None:
    """Placeholder until a native parser is wired."""
    return None


async def ensure_parser_initialized() -> None:
    """No-op compatibility shim (TS pure parser needs no init)."""
    return None


def get_parser_module() -> ParserModule | None:
    global _MODULE
    if _MODULE is None:

        class _Mod:
            parse = staticmethod(_default_parse)

        _MODULE = _Mod()  # type: ignore[assignment]
    return _MODULE


def set_parser_module(module: ParserModule | None) -> None:
    """Test hook to inject a real parser implementation."""
    global _MODULE
    _MODULE = module


async def parse_source(source: str, timeout_ms: float | None = None) -> TsNode | None:
    """Parse *source* into a :class:`TsNode` tree or ``None`` if unavailable."""
    mod = get_parser_module()
    if mod is None:
        return None
    if timeout_ms is None:
        timeout_ms = _PARSE_TIMEOUT_MS
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: mod.parse(source, timeout_ms))


async def parse_command_raw(cmd: str) -> TsNode | None:
    """Entry point used by security analysis (port of parser.parseCommandRaw)."""
    return await parse_source(cmd)
