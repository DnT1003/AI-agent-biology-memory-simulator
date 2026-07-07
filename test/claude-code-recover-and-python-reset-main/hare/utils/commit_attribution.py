"""Git commit attribution tracking (`commitAttribution.ts`). — core helpers."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

INTERNAL_MODEL_REPOS: tuple[str, ...] = (
    "github.com:anthropics/claude-cli-internal",
    "github.com/anthropics/claude-cli-internal",
    "github.com:anthropics/anthropic",
    "github.com/anthropics/anthropic",
)


def sanitize_model_name(short_name: str) -> str:
    if "opus-4-6" in short_name:
        return "claude-opus-4-6"
    if "opus-4-5" in short_name:
        return "claude-opus-4-5"
    if "opus-4-1" in short_name:
        return "claude-opus-4-1"
    if "opus-4" in short_name:
        return "claude-opus-4"
    if "sonnet-4-6" in short_name:
        return "claude-sonnet-4-6"
    if "sonnet-4-5" in short_name:
        return "claude-sonnet-4-5"
    if "sonnet-4" in short_name:
        return "claude-sonnet-4"
    if "sonnet-3-7" in short_name:
        return "claude-sonnet-3-7"
    if "haiku-4-5" in short_name:
        return "claude-haiku-4-5"
    if "haiku-3-5" in short_name:
        return "claude-haiku-3-5"
    return "claude"


def sanitize_surface_key(surface_key: str) -> str:
    idx = surface_key.rfind("/")
    if idx == -1:
        return surface_key
    surface, model = surface_key[:idx], surface_key[idx + 1 :]
    return f"{surface}/{sanitize_model_name(model)}"


def compute_content_hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def get_client_surface() -> str:
    import os

    return os.environ.get("CLAUDE_CODE_ENTRYPOINT", "cli")


@dataclass
class AttributionState:
    file_states: dict[str, Any] = field(default_factory=dict)
    session_baselines: dict[str, dict[str, Any]] = field(default_factory=dict)
    surface: str = field(default_factory=get_client_surface)
    starting_head_sha: str | None = None
    prompt_count: int = 0
    prompt_count_at_last_commit: int = 0
    permission_prompt_count: int = 0
    permission_prompt_count_at_last_commit: int = 0
    escape_count: int = 0
    escape_count_at_last_commit: int = 0


def create_empty_attribution_state() -> AttributionState:
    return AttributionState()


async def calculate_commit_attribution(
    states: list[AttributionState],
    staged_files: list[str],
) -> dict[str, Any]:
    """Stub: combine with git diff + `generated_files` when wiring."""
    return {
        "version": 1,
        "summary": {
            "claudePercent": 0,
            "claudeChars": 0,
            "humanChars": 0,
            "surfaces": list({s.surface for s in states}) if states else [],
        },
        "files": {},
        "surfaceBreakdown": {},
        "excludedGenerated": [],
        "sessions": [],
    }
