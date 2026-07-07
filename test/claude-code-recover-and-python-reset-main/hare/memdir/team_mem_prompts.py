"""Combined memory prompt builder (port of src/memdir/teamMemPrompts.ts)."""

from __future__ import annotations

from hare.memdir.memory_types import (
    MEMORY_DRIFT_CAVEAT,
    MEMORY_FRONTMATTER_EXAMPLE,
    TRUSTING_RECALL_SECTION,
    TYPES_SECTION_COMBINED,
    WHAT_NOT_TO_SAVE_SECTION,
)
from hare.memdir.paths import get_auto_mem_path
from hare.memdir.team_mem_paths import get_team_mem_path

ENTRYPOINT_NAME = "MEMORY.md"
MAX_ENTRYPOINT_LINES = 200


def build_searching_past_context_section(_auto_dir: str) -> list[str]:
    return ["## Searching past context", "", "(stub)"]


def build_combined_memory_prompt(
    extra_guidelines: list[str] | None = None,
    skip_index: bool = False,
) -> str:
    auto_dir = get_auto_mem_path()
    team_dir = get_team_mem_path()
    dirs_guidance = "Both directories are created as needed."
    how_to_save = (
        [
            "## How to save memories",
            "",
            "Write each memory to its own file ...",
            "",
            *MEMORY_FRONTMATTER_EXAMPLE,
        ]
        if skip_index
        else [
            "## How to save memories",
            "",
            "**Step 1** — write the memory file ...",
            "",
            *MEMORY_FRONTMATTER_EXAMPLE,
            "",
            f"**Step 2** — add a pointer in `{ENTRYPOINT_NAME}` ...",
        ]
    )
    lines = [
        "# Memory",
        "",
        f"You have persistent memory at `{auto_dir}` (private) and `{team_dir}` (team). {dirs_guidance}",
        "",
        *TYPES_SECTION_COMBINED,
        *WHAT_NOT_TO_SAVE_SECTION,
        "- You MUST avoid saving sensitive data in shared team memories.",
        "",
        *how_to_save,
        "",
        "## When to access memories",
        "- When relevant, or when the user asks.",
        MEMORY_DRIFT_CAVEAT,
        "",
        *TRUSTING_RECALL_SECTION,
        *(extra_guidelines or []),
        "",
        *build_searching_past_context_section(auto_dir),
    ]
    return "\n".join(lines)
