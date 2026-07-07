"""Side queries outside the main loop (port of sideQuery.ts)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class SideQueryOptions:
    model: str
    messages: list[dict[str, Any]]
    query_source: str
    system: str | list[dict[str, Any]] | None = None
    tools: list[Any] | None = None
    tool_choice: Any = None
    output_format: Any = None
    max_tokens: int = 1024
    max_retries: int = 2
    signal: Any = None
    skip_system_prompt_prefix: bool = False
    temperature: float | None = None
    thinking: int | bool | None = None
    stop_sequences: list[str] | None = None


async def side_query(opts: SideQueryOptions) -> Any:
    """
    Lightweight API wrapper for side queries (fingerprint, betas, metadata).
    Wire `hare.services.api.client` + `claude` when integrating.
    """
    raise NotImplementedError(
        "side_query: connect get_anthropic_client and beta.messages.create"
    )
