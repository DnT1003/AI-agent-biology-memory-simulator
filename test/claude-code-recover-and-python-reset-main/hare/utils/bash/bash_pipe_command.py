"""Rearrange piped commands for stdin redirect ordering. Port of: bashPipeCommand.ts"""

from __future__ import annotations

import shlex


def quote_with_eval_stdin_redirect(command: str) -> str:
    """Fallback: single-quote entire command for eval (stub)."""
    return f"eval {shlex.quote(command)}"


def rearrange_pipe_command(command: str) -> str:
    """
    Place stdin redirect after first pipeline segment.
    Full parity requires shell-quote tokenization — stub forwards to eval fallback
    when parsing is unsafe.
    """
    if "`" in command or "$(" in command:
        return quote_with_eval_stdin_redirect(command)
    if "|" not in command:
        return quote_with_eval_stdin_redirect(command)
    return quote_with_eval_stdin_redirect(command)
