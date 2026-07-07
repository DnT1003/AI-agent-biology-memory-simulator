"""Memory taxonomy and prompt sections (port of src/memdir/memoryTypes.ts)."""

from __future__ import annotations

from typing import Literal

MemoryType = Literal["user", "feedback", "project", "reference"]

MEMORY_TYPES: tuple[str, ...] = ("user", "feedback", "project", "reference")


def parse_memory_type(raw: object) -> MemoryType | None:
    if not isinstance(raw, str):
        return None
    return raw if raw in MEMORY_TYPES else None  # type: ignore[return-value]


# Full prose lives in the TS source; keep representative headers for tests/search.
TYPES_SECTION_COMBINED: list[str] = [
    "## Types of memory",
    "",
    "There are several discrete types of memory ...",
]

WHAT_NOT_TO_SAVE_SECTION: list[str] = [
    "## What NOT to save in memory",
    "",
    "- Code patterns, conventions, architecture ...",
]

MEMORY_DRIFT_CAVEAT = (
    "- Memory records can become stale over time. Use memory as context ..."
)

WHEN_TO_ACCESS_SECTION: list[str] = [
    "## When to access memories",
    "- When memories seem relevant ...",
    MEMORY_DRIFT_CAVEAT,
]

TRUSTING_RECALL_SECTION: list[str] = [
    "## Before recommending from memory",
    "",
    "A memory that names a specific function, file, or flag is a claim ...",
]

MEMORY_FRONTMATTER_EXAMPLE: list[str] = [
    "```markdown",
    "---",
    "name: {{memory name}}",
    "description: {{one-line description}}",
    "type: {{one of " + ", ".join(MEMORY_TYPES) + "}}",
    "---",
    "",
    "{{memory content}}",
    "```",
]

TYPES_SECTION_INDIVIDUAL: list[str] = [
    "## Types of memory",
    "",
    "There are several discrete types of memory ...",
]
