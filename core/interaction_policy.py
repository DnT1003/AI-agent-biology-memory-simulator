"""Pure request-policy helpers shared by transports and the cognitive engine."""

from __future__ import annotations

from collections.abc import Iterable


def is_explicit_private_input(
    user_input: str,
    commands: Iterable[object],
) -> bool:
    """Return whether input starts with an explicitly private local command."""
    normalized = (user_input or "").strip().lower()
    for raw_command in commands:
        command = str(raw_command).strip().lower()
        if not command:
            continue
        if normalized == command:
            return True
        if (
            normalized.startswith(command)
            and normalized[len(command):len(command) + 1].isspace()
        ):
            return True
    return False


__all__ = ["is_explicit_private_input"]
