"""
Query dependency injection.

Port of: src/query/deps.ts
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Callable, Awaitable


@dataclass
class QueryDeps:
    """I/O dependencies for query(). Tests can inject fakes."""
    call_model: Callable[..., Awaitable[Any]] | None = None
    microcompact: Callable[..., Awaitable[Any]] | None = None
    autocompact: Callable[..., Awaitable[Any]] | None = None
    uuid_fn: Callable[[], str] = lambda: str(uuid.uuid4())


def production_deps() -> QueryDeps:
    return QueryDeps(
        call_model=None,  # Resolved at runtime
        microcompact=None,
        autocompact=None,
        uuid_fn=lambda: str(uuid.uuid4()),
    )
