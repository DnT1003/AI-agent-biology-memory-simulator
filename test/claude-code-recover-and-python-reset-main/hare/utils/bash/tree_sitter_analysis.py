"""
Tree-sitter AST analysis utilities for bash command security validation.

Port of: src/utils/bash/treeSitterAnalysis.ts

Operates on plain dict-like node trees (type, text, start_index, end_index, children)
as produced by the native NAPI parser or a compatible stub.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class QuoteContext:
    """Quote-stripped views of command text for validation."""

    with_double_quotes: str
    fully_unquoted: str
    unquoted_keep_quote_chars: str


@dataclass
class CompoundStructure:
    has_compound_operators: bool
    has_pipeline: bool
    has_subshell: bool
    has_command_group: bool
    operators: list[str]
    segments: list[str]


@dataclass
class DangerousPatterns:
    has_command_substitution: bool
    has_process_substitution: bool
    has_parameter_expansion: bool
    has_heredoc: bool
    has_comment: bool


@dataclass
class TreeSitterAnalysis:
    quote_context: QuoteContext
    compound_structure: CompoundStructure
    has_actual_operator_nodes: bool
    dangerous_patterns: DangerousPatterns


@dataclass
class _QuoteSpans:
    raw: list[tuple[int, int]]
    ansi_c: list[tuple[int, int]]
    double: list[tuple[int, int]]
    heredoc: list[tuple[int, int]]


def _normalize_node(node: Any) -> Any:
    """Accept TS-style camelCase or Python snake_case keys."""
    if isinstance(node, dict):
        children = node.get("children") or []
        return _DictNodeAdapter(node, children)
    return node


class _DictNodeAdapter:
    __slots__ = ("_d", "children")

    def __init__(self, d: dict[str, Any], children: list[Any]) -> None:
        self._d = d
        self.children = children

    @property
    def type(self) -> str:
        return str(self._d.get("type", ""))

    @property
    def text(self) -> str:
        return str(self._d.get("text", ""))

    @property
    def start_index(self) -> int:
        return int(self._d.get("startIndex", self._d.get("start_index", 0)))

    @property
    def end_index(self) -> int:
        return int(self._d.get("endIndex", self._d.get("end_index", 0)))

    @property
    def child_count(self) -> int:
        return int(self._d.get("childCount", self._d.get("child_count", len(self.children))))


def _collect_quote_spans(
    node: Any,
    out: _QuoteSpans,
    in_double: bool,
) -> None:
    n = _normalize_node(node)
    nt = n.type

    if nt == "raw_string":
        out.raw.append((n.start_index, n.end_index))
        return
    if nt == "ansi_c_string":
        out.ansi_c.append((n.start_index, n.end_index))
        return
    if nt == "string":
        if not in_double:
            out.double.append((n.start_index, n.end_index))
        for child in n.children:
            if child is not None:
                _collect_quote_spans(child, out, True)
        return
    if nt == "heredoc_redirect":
        is_quoted = False
        for child in n.children:
            if child is None:
                continue
            cn = _normalize_node(child)
            if cn.type == "heredoc_start":
                first = cn.text[0] if cn.text else ""
                is_quoted = first in ("'", '"', "\\")
                break
        if is_quoted:
            out.heredoc.append((n.start_index, n.end_index))
            return
        # Unquoted: recurse
        pass

    for child in n.children:
        if child is not None:
            _collect_quote_spans(child, out, in_double)


def _build_position_set(spans: list[tuple[int, int]]) -> set[int]:
    s: set[int] = set()
    for start, end in spans:
        for i in range(start, end):
            s.add(i)
    return s


def _drop_contained_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for i, span in enumerate(spans):
        s0, s1 = span
        contained = False
        for j, other in enumerate(spans):
            if i == j:
                continue
            o0, o1 = other
            if o0 <= s0 and o1 >= s1 and (o0 < s0 or o1 > s1):
                contained = True
                break
        if not contained:
            out.append(span)
    return out


def _remove_spans(command: str, spans: list[tuple[int, int]]) -> str:
    if not spans:
        return command
    sorted_spans = sorted(_drop_contained_spans(spans), key=lambda x: x[0], reverse=True)
    result = command
    for start, end in sorted_spans:
        result = result[:start] + result[end:]
    return result


def _drop_contained_spans_4(
    spans: list[tuple[int, int, str, str]],
) -> list[tuple[int, int, str, str]]:
    out: list[tuple[int, int, str, str]] = []
    for i, span in enumerate(spans):
        s0, s1 = span[0], span[1]
        contained = False
        for j, other in enumerate(spans):
            if i == j:
                continue
            o0, o1 = other[0], other[1]
            if o0 <= s0 and o1 >= s1 and (o0 < s0 or o1 > s1):
                contained = True
                break
        if not contained:
            out.append(span)
    return out


def _replace_spans_keep_quotes(
    command: str,
    spans: list[tuple[int, int, str, str]],
) -> str:
    if not spans:
        return command
    items = sorted(_drop_contained_spans_4(spans), key=lambda x: x[0], reverse=True)
    result = command
    for start, end, open_q, close_q in items:
        result = result[:start] + open_q + close_q + result[end:]
    return result


def extract_quote_context(root_node: Any, command: str) -> QuoteContext:
    spans = _QuoteSpans(raw=[], ansi_c=[], double=[], heredoc=[])
    _collect_quote_spans(root_node, spans, False)
    single_quote_spans = spans.raw
    ansi_c_spans = spans.ansi_c
    double_quote_spans = spans.double
    quoted_heredoc_spans = spans.heredoc
    all_quote_spans = (
        single_quote_spans + ansi_c_spans + double_quote_spans + quoted_heredoc_spans
    )

    single_quote_set = _build_position_set(
        single_quote_spans + ansi_c_spans + quoted_heredoc_spans
    )
    double_quote_delim_set: set[int] = set()
    for start, end in double_quote_spans:
        double_quote_delim_set.add(start)
        double_quote_delim_set.add(end - 1)
    with_double = ""
    for i, ch in enumerate(command):
        if i in single_quote_set:
            continue
        if i in double_quote_delim_set:
            continue
        with_double += ch

    fully_unquoted = _remove_spans(command, list(all_quote_spans))

    spans_with_quote_chars: list[tuple[int, int, str, str]] = []
    for start, end in single_quote_spans:
        spans_with_quote_chars.append((start, end, "'", "'"))
    for start, end in ansi_c_spans:
        spans_with_quote_chars.append((start, end, "$'", "'"))
    for start, end in double_quote_spans:
        spans_with_quote_chars.append((start, end, '"', '"'))
    for start, end in quoted_heredoc_spans:
        spans_with_quote_chars.append((start, end, "", ""))
    unquoted_keep = _replace_spans_keep_quotes(command, spans_with_quote_chars)

    return QuoteContext(
        with_double_quotes=with_double,
        fully_unquoted=fully_unquoted,
        unquoted_keep_quote_chars=unquoted_keep,
    )


def extract_compound_structure(root_node: Any, command: str) -> CompoundStructure:
    n = _normalize_node(root_node)
    operators: list[str] = []
    segments: list[str] = []
    has_subshell = False
    has_command_group = False
    has_pipeline = False

    def walk_top_level(node: Any) -> None:
        nonlocal has_subshell, has_command_group, has_pipeline
        nn = _normalize_node(node)
        for child in nn.children:
            if child is None:
                continue
            c = _normalize_node(child)
            ct = c.type

            if ct == "list":
                for list_child in c.children:
                    if list_child is None:
                        continue
                    lc = _normalize_node(list_child)
                    lct = lc.type
                    if lct in ("&&", "||"):
                        operators.append(lct)
                    elif lct in ("list", "redirected_statement"):
                        walk_top_level({"type": "program", "children": [list_child]})
                    elif lct == "pipeline":
                        has_pipeline = True
                        segments.append(lc.text)
                    elif lct == "subshell":
                        has_subshell = True
                        segments.append(lc.text)
                    elif lct == "compound_statement":
                        has_command_group = True
                        segments.append(lc.text)
                    else:
                        segments.append(lc.text)
            elif ct == ";":
                operators.append(";")
            elif ct == "pipeline":
                has_pipeline = True
                segments.append(c.text)
            elif ct == "subshell":
                has_subshell = True
                segments.append(c.text)
            elif ct == "compound_statement":
                has_command_group = True
                segments.append(c.text)
            elif ct in ("command", "declaration_command", "variable_assignment"):
                segments.append(c.text)
            elif ct == "redirected_statement":
                found_inner = False
                for inner in c.children:
                    if inner is None:
                        continue
                    inn = _normalize_node(inner)
                    if inn.type == "file_redirect":
                        continue
                    found_inner = True
                    walk_top_level({"type": "program", "children": [inner]})
                if not found_inner:
                    segments.append(c.text)
            elif ct == "negated_command":
                segments.append(c.text)
                walk_top_level(c)
            elif ct in (
                "if_statement",
                "while_statement",
                "for_statement",
                "case_statement",
                "function_definition",
            ):
                segments.append(c.text)
                walk_top_level(c)

    walk_top_level(n)
    if not segments:
        segments = [command]

    return CompoundStructure(
        has_compound_operators=len(operators) > 0,
        has_pipeline=has_pipeline,
        has_subshell=has_subshell,
        has_command_group=has_command_group,
        operators=operators,
        segments=segments,
    )


def has_actual_operator_nodes(root_node: Any) -> bool:
    n = _normalize_node(root_node)

    def walk(node: Any) -> bool:
        nn = _normalize_node(node)
        if nn.type in (";", "&&", "||"):
            return True
        if nn.type == "list":
            return True
        for child in nn.children:
            if child is not None and walk(child):
                return True
        return False

    return walk(n)


def extract_dangerous_patterns(root_node: Any) -> DangerousPatterns:
    n = _normalize_node(root_node)
    has_cmdsub = False
    has_procs = False
    has_param = False
    has_heredoc = False
    has_comment = False

    def walk(node: Any) -> None:
        nonlocal has_cmdsub, has_procs, has_param, has_heredoc, has_comment
        nn = _normalize_node(node)
        match nn.type:
            case "command_substitution":
                has_cmdsub = True
            case "process_substitution":
                has_procs = True
            case "expansion":
                has_param = True
            case "heredoc_redirect":
                has_heredoc = True
            case "comment":
                has_comment = True
        for child in nn.children:
            if child is not None:
                walk(child)

    walk(n)
    return DangerousPatterns(
        has_command_substitution=has_cmdsub,
        has_process_substitution=has_procs,
        has_parameter_expansion=has_param,
        has_heredoc=has_heredoc,
        has_comment=has_comment,
    )


def analyze_command(root_node: Any, command: str) -> TreeSitterAnalysis:
    return TreeSitterAnalysis(
        quote_context=extract_quote_context(root_node, command),
        compound_structure=extract_compound_structure(root_node, command),
        has_actual_operator_nodes=has_actual_operator_nodes(root_node),
        dangerous_patterns=extract_dangerous_patterns(root_node),
    )
