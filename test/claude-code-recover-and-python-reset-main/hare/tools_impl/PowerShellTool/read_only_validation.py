"""Read-only session validation for PowerShell. Port of: src/tools/PowerShellTool/readOnlyValidation.ts"""

from __future__ import annotations

_WRITERS = ("set-content", "out-file", "move-item", "remove-item", "ni ", "new-item")


def violates_read_only_mode(command: str) -> bool:
    low = command.lower()
    return any(w in low for w in _WRITERS)
