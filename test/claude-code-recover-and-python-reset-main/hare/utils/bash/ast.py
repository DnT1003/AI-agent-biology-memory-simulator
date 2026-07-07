"""
AST-based bash command analysis (tree-sitter compatible).

Port of: src/utils/bash/ast.ts (types, entrypoints, and stable analytics IDs).

Full argv extraction from AST is not replicated here; analysis fails closed
with ``too-complex`` until wired to the native parser pipeline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal, TypeAlias, Union

from hare.utils.bash.bash_parser import PARSE_ABORTED, TsNode, parse_command_raw

# Order matches TS DANGEROUS_TYPES Set iteration for stable node_type_id indices.
_DANGEROUS_TYPE_IDS: tuple[str, ...] = (
    "command_substitution",
    "process_substitution",
    "expansion",
    "simple_expansion",
    "brace_expression",
    "subshell",
    "compound_statement",
    "for_statement",
    "while_statement",
    "until_statement",
    "if_statement",
    "case_statement",
    "function_definition",
    "test_command",
    "ansi_c_string",
    "translated_string",
    "herestring_redirect",
    "heredoc_redirect",
)

Node: TypeAlias = TsNode

CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
UNICODE_WHITESPACE_RE = re.compile(
    r"[\u00a0\u1680\u2000-\u200b\u2028\u2029\u202f\u205f\u3000\ufeff]"
)
BACKSLASH_WHITESPACE_RE = re.compile(r"\\[ \t]|[^ \t\n\\]\\\n")
ZSH_TILDE_BRACKET_RE = re.compile(r"~\[")
ZSH_EQUALS_EXPANSION_RE = re.compile(r"(?:^|[\s;&|])=[a-zA-Z_]")
BRACE_WITH_QUOTE_RE = re.compile(r"\{[^}]*['\"]")


@dataclass
class Redirect:
    op: Literal[">", ">>", "<", "<<", ">&", ">|", "<&", "&>", "&>>", "<<<"]
    target: str
    fd: int | None = None


@dataclass
class SimpleCommand:
    argv: list[str]
    env_vars: list[tuple[str, str]]
    redirects: list[Redirect]
    text: str


ParseForSecurityResult: TypeAlias = Union[
    "ParseForSecuritySimple",
    "ParseForSecurityTooComplex",
    "ParseForSecurityUnavailable",
]


@dataclass
class ParseForSecuritySimple:
    kind: Literal["simple"] = "simple"
    commands: list[SimpleCommand] = field(default_factory=list)


@dataclass
class ParseForSecurityTooComplex:
    kind: Literal["too-complex"] = "too-complex"
    reason: str = ""
    node_type: str | None = None


@dataclass
class ParseForSecurityUnavailable:
    kind: Literal["parse-unavailable"] = "parse-unavailable"


SemanticCheckResult: TypeAlias = Union["SemanticOk", "SemanticErr"]


@dataclass
class SemanticOk:
    ok: Literal[True] = True


@dataclass
class SemanticErr:
    ok: Literal[False] = False
    reason: str = ""


def node_type_id(node_type: str | None) -> int:
    """Numeric ID for analytics (matches TS ordering)."""
    if not node_type:
        return -2
    if node_type == "ERROR":
        return -1
    try:
        idx = _DANGEROUS_TYPE_IDS.index(node_type)
    except ValueError:
        return 0
    return idx + 1


def _mask_braces_in_quoted_contexts(cmd: str) -> str:
    if "{" not in cmd:
        return cmd
    out: list[str] = []
    in_single = False
    in_double = False
    i = 0
    while i < len(cmd):
        c = cmd[i]
        if in_single:
            if c == "'":
                in_single = False
            out.append(" " if c == "{" else c)
            i += 1
        elif in_double:
            if c == "\\" and i + 1 < len(cmd) and cmd[i + 1] in ('"', "\\"):
                out.extend((c, cmd[i + 1]))
                i += 2
            else:
                if c == '"':
                    in_double = False
                out.append(" " if c == "{" else c)
                i += 1
        else:
            if c == "\\" and i + 1 < len(cmd):
                out.extend((c, cmd[i + 1]))
                i += 2
            else:
                if c == "'":
                    in_single = True
                elif c == '"':
                    in_double = True
                out.append(c)
                i += 1
    return "".join(out)


def parse_for_security_from_ast(cmd: str, root: TsNode | Any) -> ParseForSecurityResult:
    """Pre-checks + fail-closed stub (full AST walk lives in TypeScript)."""
    if CONTROL_CHAR_RE.search(cmd):
        return ParseForSecurityTooComplex(reason="Contains control characters")
    if UNICODE_WHITESPACE_RE.search(cmd):
        return ParseForSecurityTooComplex(reason="Contains Unicode whitespace")
    if BACKSLASH_WHITESPACE_RE.search(cmd):
        return ParseForSecurityTooComplex(
            reason="Contains backslash-escaped whitespace"
        )
    if ZSH_TILDE_BRACKET_RE.search(cmd):
        return ParseForSecurityTooComplex(
            reason="Contains zsh ~[ dynamic directory syntax"
        )
    if ZSH_EQUALS_EXPANSION_RE.search(cmd):
        return ParseForSecurityTooComplex(reason="Contains zsh =cmd equals expansion")
    if BRACE_WITH_QUOTE_RE.search(_mask_braces_in_quoted_contexts(cmd)):
        return ParseForSecurityTooComplex(
            reason="Contains brace with quote character (expansion obfuscation)"
        )

    trimmed = cmd.strip()
    if trimmed == "":
        return ParseForSecuritySimple(commands=[])

    if root is PARSE_ABORTED:
        return ParseForSecurityTooComplex(
            reason="Parse aborted (timeout or resource limit)",
            node_type="ERROR",
        )

    return ParseForSecurityTooComplex(
        reason="Full AST argv extraction not ported; use native CLI path",
    )


async def parse_for_security(cmd: str) -> ParseForSecurityResult:
    if cmd == "":
        return ParseForSecuritySimple(commands=[])
    root = await parse_command_raw(cmd)
    if root is None:
        return ParseForSecurityUnavailable()
    return parse_for_security_from_ast(cmd, root)


def check_semantics(commands: list[SimpleCommand]) -> SemanticCheckResult:
    """Post-argv semantic checks (minimal port — fail closed on suspicious argv)."""
    proc_environ = re.compile(r"/proc/.*/environ")
    newline_hash = re.compile(r"\n[ \t]*#")
    for cmd in commands:
        for arg in cmd.argv:
            if proc_environ.search(arg):
                return SemanticErr(reason="Argument references /proc/*/environ")
            if newline_hash.search(arg):
                return SemanticErr(
                    reason="Argument contains newline followed by shell comment"
                )
    return SemanticOk()
