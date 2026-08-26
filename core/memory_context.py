"""Request-local access policy for persistent memory.

Backend locality and memory audience are intentionally separate concepts:
``local_only`` controls network capability, while ``private_ephemeral``
forbids persistence altogether.  The current product has one authenticated
owner, so the only durable scopes are agent-owned knowledge and owner-related
memory; this module does not pretend to provide multi-user isolation.
"""

from __future__ import annotations

import contextvars
import re
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from typing import Iterator


class MemoryScope(str, Enum):
    AGENT = "agent"
    OWNER = "owner"


class MemoryPrivacy(str, Enum):
    STANDARD = "standard"
    LEGACY_UNKNOWN = "legacy_unknown"


class MemoryAccessError(RuntimeError):
    """A memory operation violates the active request policy."""

    def __init__(self, operation: str, reason: str) -> None:
        self.operation = str(operation or "memory")
        self.reason = str(reason or "denied")
        super().__init__(
            f"Memory access denied (operation={self.operation}, reason={self.reason})"
        )


_SAFE_SOURCE = re.compile(r"[^A-Za-z0-9_.:-]+")


def sanitize_memory_identifier(value: object, *, fallback: str = "unknown") -> str:
    """Return bounded correlation metadata without retaining arbitrary text."""

    normalized = _SAFE_SOURCE.sub("_", str(value or "").strip())[:128]
    return normalized or fallback


@dataclass(frozen=True, slots=True)
class MemoryAccessContext:
    read_scopes: tuple[MemoryScope, ...] = (
        MemoryScope.AGENT,
        MemoryScope.OWNER,
    )
    write_scope: MemoryScope | None = MemoryScope.OWNER
    private_ephemeral: bool = False
    local_only: bool = False
    origin_kind: str = "runtime"
    origin_source: str = "unknown"
    source_event_id: str | None = None

    def __post_init__(self) -> None:
        scopes: list[MemoryScope] = []
        for scope in self.read_scopes:
            normalized = scope if isinstance(scope, MemoryScope) else MemoryScope(scope)
            if normalized not in scopes:
                scopes.append(normalized)
        object.__setattr__(self, "read_scopes", tuple(scopes))
        if self.write_scope is not None and not isinstance(
            self.write_scope, MemoryScope
        ):
            object.__setattr__(self, "write_scope", MemoryScope(self.write_scope))
        if (
            self.write_scope is not None
            and self.write_scope not in self.read_scopes
        ):
            raise ValueError("write_scope must be included in read_scopes")
        object.__setattr__(self, "private_ephemeral", bool(self.private_ephemeral))
        object.__setattr__(self, "local_only", bool(self.local_only))
        object.__setattr__(
            self,
            "origin_kind",
            sanitize_memory_identifier(self.origin_kind, fallback="runtime"),
        )
        object.__setattr__(
            self,
            "origin_source",
            sanitize_memory_identifier(self.origin_source),
        )
        if self.source_event_id is not None:
            object.__setattr__(
                self,
                "source_event_id",
                sanitize_memory_identifier(self.source_event_id),
            )


DEFAULT_MEMORY_ACCESS_CONTEXT = MemoryAccessContext()
_ACTIVE_MEMORY_CONTEXT: contextvars.ContextVar[MemoryAccessContext] = (
    contextvars.ContextVar(
        "aura_memory_access_context",
        default=DEFAULT_MEMORY_ACCESS_CONTEXT,
    )
)


def current_memory_context() -> MemoryAccessContext:
    return _ACTIVE_MEMORY_CONTEXT.get()


def activate_memory_context(context: MemoryAccessContext):
    if not isinstance(context, MemoryAccessContext):
        raise TypeError("context must be MemoryAccessContext")
    return _ACTIVE_MEMORY_CONTEXT.set(context)


def reset_memory_context(token) -> None:
    _ACTIVE_MEMORY_CONTEXT.reset(token)


@contextmanager
def memory_context_scope(
    context: MemoryAccessContext,
) -> Iterator[MemoryAccessContext]:
    token = activate_memory_context(context)
    try:
        yield context
    finally:
        reset_memory_context(token)


def interaction_memory_context(
    *,
    source: object,
    request_id: object,
    private_ephemeral: bool,
    local_only: bool,
) -> MemoryAccessContext:
    return MemoryAccessContext(
        read_scopes=()
        if private_ephemeral
        else (MemoryScope.AGENT, MemoryScope.OWNER),
        write_scope=None if private_ephemeral else MemoryScope.OWNER,
        private_ephemeral=private_ephemeral,
        local_only=local_only,
        origin_kind="interaction",
        origin_source=sanitize_memory_identifier(source),
        source_event_id=(
            None
            if private_ephemeral
            else sanitize_memory_identifier(request_id)
        ),
    )


def maintenance_memory_context(
    *,
    origin_kind: str,
    origin_source: str = "runtime",
    source_event_id: object | None = None,
) -> MemoryAccessContext:
    """Allow maintenance to update existing records in either durable scope."""

    return MemoryAccessContext(
        read_scopes=(MemoryScope.AGENT, MemoryScope.OWNER),
        write_scope=None,
        origin_kind=origin_kind,
        origin_source=origin_source,
        source_event_id=(
            None
            if source_event_id is None
            else sanitize_memory_identifier(source_event_id)
        ),
    )


__all__ = [
    "DEFAULT_MEMORY_ACCESS_CONTEXT",
    "MemoryAccessContext",
    "MemoryAccessError",
    "MemoryPrivacy",
    "MemoryScope",
    "activate_memory_context",
    "current_memory_context",
    "interaction_memory_context",
    "maintenance_memory_context",
    "memory_context_scope",
    "reset_memory_context",
    "sanitize_memory_identifier",
]
