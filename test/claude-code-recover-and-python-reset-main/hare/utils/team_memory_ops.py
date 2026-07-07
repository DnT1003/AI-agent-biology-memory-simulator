"""Team memory path checks (port of teamMemoryOps.ts)."""

from __future__ import annotations

from typing import Any

FILE_EDIT_TOOL_NAME = "Edit"
FILE_WRITE_TOOL_NAME = "Write"


def is_team_mem_file(path: str) -> bool:
    """Stub: replace with memdir team paths when wired."""
    return ".claude" in path and "team" in path.lower()


def is_team_memory_search(tool_input: Any) -> bool:
    if not isinstance(tool_input, dict):
        return False
    p = tool_input.get("path")
    return isinstance(p, str) and is_team_mem_file(p)


def is_team_memory_write_or_edit(tool_name: str, tool_input: Any) -> bool:
    if tool_name not in (FILE_WRITE_TOOL_NAME, FILE_EDIT_TOOL_NAME):
        return False
    if not isinstance(tool_input, dict):
        return False
    fp = tool_input.get("file_path") or tool_input.get("path")
    return isinstance(fp, str) and is_team_mem_file(fp)


def append_team_memory_summary_parts(
    memory_counts: dict[str, int],
    is_active: bool,
    parts: list[str],
) -> None:
    tr = memory_counts.get("team_memory_read_count") or 0
    ts = memory_counts.get("team_memory_search_count") or 0
    tw = memory_counts.get("team_memory_write_count") or 0
    if tr > 0:
        if is_active:
            v = "Recalling" if not parts else "recalling"
        else:
            v = "Recalled" if not parts else "recalled"
        parts.append(f"{v} {tr} team {'memory' if tr == 1 else 'memories'}")
    if ts > 0:
        if is_active:
            v = "Searching" if not parts else "searching"
        else:
            v = "Searched" if not parts else "searched"
        parts.append(f"{v} team memories")
    if tw > 0:
        if is_active:
            v = "Writing" if not parts else "writing"
        else:
            v = "Wrote" if not parts else "wrote"
        parts.append(f"{v} {tw} team {'memory' if tw == 1 else 'memories'}")
