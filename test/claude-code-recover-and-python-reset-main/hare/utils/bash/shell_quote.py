"""
Safe wrappers around shell tokenization / quoting (shell-quote in TS).

Port of: src/utils/bash/shellQuote.ts

Uses :py:mod:`shlex` as a stand-in when a full shell-quote port is unavailable.
"""

from __future__ import annotations

import json
import re
import shlex
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Sequence, Union

ParseEntry = Union[str, dict[str, Any]]


def _log_error(error: BaseException) -> None:
    """Stub for ../log.logError."""
    del error


@dataclass
class ShellParseSuccess:
    success: Literal[True] = True
    tokens: list[ParseEntry] = field(default_factory=list)


@dataclass
class ShellParseFailure:
    success: Literal[False] = False
    error: str = ""


ShellParseResult = ShellParseSuccess | ShellParseFailure


@dataclass
class ShellQuoteSuccess:
    success: Literal[True] = True
    quoted: str = ""


@dataclass
class ShellQuoteFailure:
    success: Literal[False] = False
    error: str = ""


ShellQuoteResult = ShellQuoteSuccess | ShellQuoteFailure


def _parse_shell_quote_stub(
    cmd: str,
    env: dict[str, str | None] | Callable[[str], str | None] | None = None,
) -> list[ParseEntry]:
    """Minimal tokenizer: split on whitespace outside quotes via shlex."""
    del env
    try:
        return shlex.split(cmd, posix=True)
    except ValueError:
        return cmd.split()


def try_parse_shell_command(
    cmd: str,
    env: dict[str, str | None] | Callable[[str], str | None] | None = None,
) -> ShellParseResult:
    try:
        tokens: list[ParseEntry] = _parse_shell_quote_stub(cmd, env)
        return ShellParseSuccess(tokens=tokens)
    except Exception as error:
        _log_error(error)
        return ShellParseFailure(error=str(error))


def try_quote_shell_args(args: Sequence[Any]) -> ShellQuoteResult:
    try:
        validated: list[str] = []
        for index, arg in enumerate(args):
            if arg is None:
                validated.append(str(arg))
                continue
            t = type(arg).__name__
            if isinstance(arg, str):
                validated.append(arg)
            elif isinstance(arg, (int, float, bool)):
                validated.append(str(arg))
            elif isinstance(arg, (dict, list)):
                raise TypeError(
                    f"Cannot quote argument at index {index}: object values are not supported"
                )
            else:
                raise TypeError(
                    f"Cannot quote argument at index {index}: unsupported type {t}"
                )
        quoted = shlex.join(validated) if hasattr(shlex, "join") else " ".join(
            shlex.quote(a) for a in validated
        )
        return ShellQuoteSuccess(quoted=quoted)
    except Exception as error:
        _log_error(error)
        return ShellQuoteFailure(
            error=str(error) if isinstance(error, Exception) else "Unknown quote error"
        )


def has_malformed_tokens(command: str, parsed: list[ParseEntry]) -> bool:
    in_single = False
    in_double = False
    double_count = 0
    single_count = 0
    i = 0
    while i < len(command):
        c = command[i]
        if c == "\\" and not in_single:
            i += 2
            continue
        if c == '"' and not in_single:
            double_count += 1
            in_double = not in_double
        elif c == "'" and not in_double:
            single_count += 1
            in_single = not in_single
        i += 1
    if double_count % 2 != 0 or single_count % 2 != 0:
        return True

    for entry in parsed:
        if not isinstance(entry, str):
            continue
        if entry.count("{") != entry.count("}"):
            return True
        if entry.count("(") != entry.count(")"):
            return True
        if entry.count("[") != entry.count("]"):
            return True
        dq = re.findall(r'(?<!\\)"', entry)
        if len(dq) % 2 != 0:
            return True
        sq = re.findall(r"(?<!\\)'", entry)
        if len(sq) % 2 != 0:
            return True
    return False


def has_shell_quote_single_quote_bug(command: str) -> bool:
    """Detect patterns that confuse naive parsers' single-quote handling."""
    in_single_quote = False
    in_double_quote = False
    i = 0
    while i < len(command):
        char = command[i]
        if char == "\\" and not in_single_quote:
            i += 2
            continue
        if char == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            i += 1
            continue
        if char == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            if not in_single_quote:
                backslash_count = 0
                j = i - 1
                while j >= 0 and command[j] == "\\":
                    backslash_count += 1
                    j -= 1
                if backslash_count > 0 and backslash_count % 2 == 1:
                    return True
                if (
                    backslash_count > 0
                    and backslash_count % 2 == 0
                    and "'" in command[i + 1 :]
                ):
                    return True
            i += 1
            continue
        i += 1
    return False


def quote(args: Sequence[Any]) -> str:
    result = try_quote_shell_args(list(args))
    if result.success:
        return result.quoted
    string_args: list[str] = []
    for arg in args:
        if arg is None:
            string_args.append(str(arg))
            continue
        if isinstance(arg, (str, int, float, bool)):
            string_args.append(str(arg))
        else:
            string_args.append(json.dumps(arg, default=str))
    try:
        return (
            shlex.join(string_args)
            if hasattr(shlex, "join")
            else " ".join(shlex.quote(a) for a in string_args)
        )
    except Exception as error:
        _log_error(error)
        raise RuntimeError("Failed to quote shell arguments safely") from error
