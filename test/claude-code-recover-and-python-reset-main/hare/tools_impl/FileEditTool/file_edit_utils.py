"""Helpers for applying edits and normalizing paths. Port of: src/tools/FileEditTool/utils.ts"""

from __future__ import annotations

from pathlib import Path


def normalize_edit_path(raw: str, cwd: Path) -> Path:
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = cwd / p
    return p.resolve()


def count_occurrences(haystack: str, needle: str) -> int:
    if not needle:
        return 0
    return haystack.count(needle)
