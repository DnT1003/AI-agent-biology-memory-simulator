"""Durable, privacy-aware event journal for offline audit and replay.

The journal stores one immutable JSON document per event.  A write becomes
visible only after the complete document has been flushed and atomically moved
into the run's ``events`` directory.  This deliberately mirrors the durable
chat spool instead of relying on SQLite WAL semantics that are unsafe on some
shared filesystems.

The hash chain is *corruption evident*.  When ``auth_key`` is supplied it is
also authenticated with HMAC-SHA256; without a key an attacker who can rewrite
the directory can recompute the plain SHA-256 chain.
"""

from __future__ import annotations

import contextvars
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping, Optional

from core.logger import get_logger


logger = get_logger("event_journal")

SCHEMA_VERSION = 1
KIND_VERSION = 1
GENESIS_HASH = "0" * 64
STANDARD_PRIVACY = "standard"
PRIVATE_EPHEMERAL = "private_ephemeral"

_EVENT_FILENAME_RE = re.compile(
    r"^(?P<sequence>[0-9]{20})-(?P<event_id>[0-9a-f]{32})\.json$",
    re.ASCII,
)
_RUN_ID_RE = re.compile(r"^[0-9]{20}-[0-9a-f]{32}$", re.ASCII)
_EVENT_ID_RE = re.compile(r"^[0-9a-f]{32}$", re.ASCII)
_KIND_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$", re.ASCII)
_CORRELATION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,191}$", re.ASCII)

_EVENT_ENVELOPE_FIELDS = frozenset(
    {
        "schema",
        "sequence",
        "event_id",
        "event_type",
        "kind_version",
        "occurred_at_ns",
        "writer_id",
        "monotonic_ns",
        "trace_id",
        "request_id",
        "correlation_id",
        "causation_id",
        "source",
        "privacy",
        "outcome",
        "payload",
        "previous_hash",
        "hash_algorithm",
        "event_hash",
    }
)

_ALLOWED_SOURCES = frozenset(
    {
        "unknown",
        "cli",
        "web",
        "discord",
        "autonomous",
        "system",
        "dashboard",
        "test",
        "sync",
        "async",
    }
)
_ALLOWED_OUTCOMES = frozenset(
    {
        "accepted",
        "started",
        "succeeded",
        "failed",
        "cancelled",
        "rejected",
        "durable",
        "acked",
        "skipped",
        "recovered",
    }
)

# Runtime event schemas are intentionally narrow.  In particular, none of the
# fields below can carry prompts, responses, tool arguments/results, URLs, or
# exception messages.  Unknown event kinds may be used only with an empty
# payload, which keeps schema evolution fail-closed until a new kind is added.
EVENT_PAYLOAD_FIELDS: Mapping[str, frozenset[str]] = {
    "journal.run_started": frozenset({"format"}),
    "journal.run_finished": frozenset({"write_failures"}),
    "journal.recovered": frozenset({"orphan_temps"}),
    "interaction.accepted": frozenset({"operation", "queue_depth"}),
    "interaction.started": frozenset({"operation", "queue_wait_ms"}),
    "interaction.finished": frozenset(
        {"operation", "duration_ms", "response_present", "error_type"}
    ),
    "runtime.state_changed": frozenset({"from_state", "to_state", "forced"}),
    "state.snapshot": frozenset({"projection", "projection_hash"}),
    "state.delta": frozenset({"before_hash", "after_hash", "patch"}),
    "inference.started": frozenset(
        {"call_id", "kind", "backend", "provider", "model", "force_local"}
    ),
    "inference.finished": frozenset(
        {
            "call_id",
            "kind",
            "backend",
            "provider",
            "model",
            "duration_ms",
            "fallback_count",
            "error_type",
        }
    ),
    "tool.started": frozenset({"call_id", "tool_name"}),
    "tool.finished": frozenset(
        {"call_id", "tool_name", "duration_ms", "error_type"}
    ),
    "tool.accounting_warning": frozenset(
        {"call_id", "tool_name", "phase", "error_type"}
    ),
    "cognitive_tick.started": frozenset({"elapsed_seconds"}),
    "cognitive_tick.finished": frozenset(
        {
            "elapsed_seconds",
            "duration_ms",
            "error_type",
            "biology_status",
            "maintenance_status",
            "phase",
        }
    ),
    "maintenance.sleep": frozenset(
        {"sleep_committed", "degraded_phase_count"}
    ),
    "delivery.durable": frozenset({"transport", "message_id"}),
    "delivery.acked": frozenset({"transport", "message_id"}),
}


class EventJournalError(RuntimeError):
    """Base class for event-journal failures."""


class JournalValidationError(EventJournalError, ValueError):
    """An event or configuration value violates the journal schema."""


class JournalCorruptionError(EventJournalError):
    """Committed journal data does not form one valid immutable chain."""

    def __init__(self, message: str, *, sequence: int | None = None):
        self.sequence = sequence
        super().__init__(message)


class JournalIOError(EventJournalError):
    """A filesystem operation failed while preserving journal state."""


class JournalLockTimeout(EventJournalError, TimeoutError):
    """The cross-process append lock could not be acquired in time."""


class JournalFull(EventJournalError):
    """The current run reached its configured immutable event bound."""


class EventConflict(EventJournalError):
    """An event ID was retried with different semantic data."""


class _DuplicateJSONKey(ValueError):
    """Internal sentinel raised by the strict journal JSON decoder."""


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            # Do not echo the key: an untrusted field name could itself carry
            # data that must not reach logs or recovery reports.
            raise _DuplicateJSONKey("Duplicate key in journal JSON object")
        value[key] = item
    return value


def _validate_event_envelope_fields(value: Mapping[str, Any]) -> None:
    try:
        envelope_fields = frozenset(value.keys())
    except (AttributeError, TypeError) as exc:
        raise JournalCorruptionError("Event envelope is not an object") from exc
    if envelope_fields != _EVENT_ENVELOPE_FIELDS:
        raise JournalCorruptionError(
            "Event envelope fields do not exactly match schema"
        )


@dataclass(frozen=True, slots=True)
class JournalContext:
    """Safe correlation metadata inherited by nested runtime operations."""

    correlation_id: str | None = None
    trace_id: str | None = None
    request_id: str | None = None
    source: str = "unknown"
    private_ephemeral: bool = False


@dataclass(frozen=True, slots=True)
class JournalEvent:
    schema: int
    sequence: int
    event_id: str
    event_type: str
    kind_version: int
    occurred_at_ns: int
    writer_id: str
    monotonic_ns: int
    trace_id: str | None
    request_id: str | None
    correlation_id: str | None
    causation_id: str | None
    source: str
    privacy: str
    outcome: str | None
    payload: Mapping[str, Any]
    previous_hash: str
    hash_algorithm: str
    event_hash: str

    @property
    def kind(self) -> str:
        """Compatibility alias used by scenario evaluators."""

        return self.event_type

    @property
    def seq(self) -> int:
        """Compatibility alias for compact reporting."""

        return self.sequence

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "sequence": self.sequence,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "kind_version": self.kind_version,
            "occurred_at_ns": self.occurred_at_ns,
            "writer_id": self.writer_id,
            "monotonic_ns": self.monotonic_ns,
            "trace_id": self.trace_id,
            "request_id": self.request_id,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "source": self.source,
            "privacy": self.privacy,
            "outcome": self.outcome,
            "payload": dict(self.payload),
            "previous_hash": self.previous_hash,
            "hash_algorithm": self.hash_algorithm,
            "event_hash": self.event_hash,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "JournalEvent":
        # Treat the envelope itself as a closed schema. Optional metadata is
        # represented by an explicit JSON null; silently accepting missing or
        # additional fields would let unreviewed data bypass the narrow
        # payload allowlist and would make schema-version replay ambiguous.
        _validate_event_envelope_fields(value)
        try:
            event = cls(
                schema=value["schema"],
                sequence=value["sequence"],
                event_id=value["event_id"],
                event_type=value["event_type"],
                kind_version=value["kind_version"],
                occurred_at_ns=value["occurred_at_ns"],
                writer_id=value["writer_id"],
                monotonic_ns=value["monotonic_ns"],
                trace_id=value.get("trace_id"),
                request_id=value.get("request_id"),
                correlation_id=value.get("correlation_id"),
                causation_id=value.get("causation_id"),
                source=value["source"],
                privacy=value["privacy"],
                outcome=value.get("outcome"),
                payload=value["payload"],
                previous_hash=value["previous_hash"],
                hash_algorithm=value["hash_algorithm"],
                event_hash=value["event_hash"],
            )
        except (KeyError, TypeError) as exc:
            raise JournalCorruptionError("Event envelope is incomplete") from exc
        _validate_committed_event(event)
        return event


@dataclass(frozen=True, slots=True)
class VerificationReport:
    valid: bool
    event_count: int
    first_sequence: int | None
    last_sequence: int | None
    head_hash: str
    error: str | None = None
    corrupt_sequence: int | None = None


@dataclass(frozen=True, slots=True)
class RecoveryReport:
    valid_events: int
    orphan_temps: int
    removed_temps: int
    corruption: str | None = None


@dataclass(slots=True)
class ActiveJournalContext:
    """Mutable request-local head carried safely by ``ContextVar``."""

    journal: "EventJournal"
    context: JournalContext
    last_event_id: str | None = None


_ACTIVE_CONTEXT: contextvars.ContextVar[ActiveJournalContext | None] = (
    contextvars.ContextVar("aura_event_journal_context", default=None)
)

_LOCKS_GUARD = threading.Lock()
_PROCESS_LOCKS: dict[str, threading.RLock] = {}


def _process_lock(path: Path) -> threading.RLock:
    key = os.path.normcase(os.fspath(path.resolve()))
    with _LOCKS_GUARD:
        lock = _PROCESS_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _PROCESS_LOCKS[key] = lock
        return lock


def canonical_json_bytes(value: Any) -> bytes:
    """Return the one canonical JSON representation accepted by the journal."""

    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise JournalValidationError("Value is not canonical finite JSON") from exc


def compute_event_hash(
    event: Mapping[str, Any], auth_key: bytes | None = None
) -> str:
    """Compute an envelope hash, excluding its ``event_hash`` field."""

    body = dict(event)
    body.pop("event_hash", None)
    serialized = canonical_json_bytes(body)
    if auth_key is not None:
        return hmac.new(auth_key, serialized, hashlib.sha256).hexdigest()
    return hashlib.sha256(serialized).hexdigest()


def _validate_json(value: Any, *, depth: int = 0) -> Any:
    if depth > 24:
        raise JournalValidationError("JSON payload nesting is too deep")
    if value is None or isinstance(value, (str, bool, int)):
        if isinstance(value, str) and len(value.encode("utf-8")) > 8_192:
            raise JournalValidationError("A journal string field is too large")
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise JournalValidationError("Journal numbers must be finite")
        return value
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise JournalValidationError("Journal object keys must be non-empty strings")
            normalized[key] = _validate_json(item, depth=depth + 1)
        return normalized
    if isinstance(value, (list, tuple)):
        if len(value) > 10_000:
            raise JournalValidationError("Journal arrays are too large")
        return [_validate_json(item, depth=depth + 1) for item in value]
    raise JournalValidationError(
        f"Unsupported journal JSON type: {type(value).__name__}"
    )


def _validate_identifier(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not _CORRELATION_RE.fullmatch(value):
        raise JournalValidationError(f"Invalid {field_name}")
    return value


def _validate_payload(event_type: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise JournalValidationError("Event payload must be an object")
    allowed = EVENT_PAYLOAD_FIELDS.get(event_type)
    keys = set(payload)
    if allowed is None and keys:
        raise JournalValidationError(
            f"Unknown event type {event_type!r} may only use an empty payload"
        )
    if allowed is not None and not keys.issubset(allowed):
        unexpected = ", ".join(sorted(keys - allowed))
        raise JournalValidationError(
            f"Event payload has unsupported field(s): {unexpected}"
        )
    return _validate_json(payload)


def _validate_committed_event(event: JournalEvent) -> None:
    if event.schema != SCHEMA_VERSION:
        raise JournalCorruptionError(
            f"Unsupported journal schema: {event.schema}", sequence=event.sequence
        )
    if isinstance(event.sequence, bool) or not isinstance(event.sequence, int) or event.sequence < 1:
        raise JournalCorruptionError("Invalid event sequence", sequence=event.sequence)
    if not isinstance(event.event_id, str) or not _EVENT_ID_RE.fullmatch(event.event_id):
        raise JournalCorruptionError("Invalid event ID", sequence=event.sequence)
    if not isinstance(event.writer_id, str) or not _EVENT_ID_RE.fullmatch(event.writer_id):
        raise JournalCorruptionError("Invalid writer ID", sequence=event.sequence)
    if not isinstance(event.event_type, str) or not _KIND_RE.fullmatch(event.event_type):
        raise JournalCorruptionError("Invalid event type", sequence=event.sequence)
    if event.kind_version != KIND_VERSION:
        raise JournalCorruptionError("Unsupported event kind version", sequence=event.sequence)
    if (
        isinstance(event.occurred_at_ns, bool)
        or not isinstance(event.occurred_at_ns, int)
        or event.occurred_at_ns < 0
    ):
        raise JournalCorruptionError("Invalid wall-clock timestamp", sequence=event.sequence)
    if (
        isinstance(event.monotonic_ns, bool)
        or not isinstance(event.monotonic_ns, int)
        or event.monotonic_ns < 0
    ):
        raise JournalCorruptionError("Invalid monotonic duration", sequence=event.sequence)
    try:
        _validate_identifier(event.trace_id, "trace_id")
        _validate_identifier(event.request_id, "request_id")
        _validate_identifier(event.correlation_id, "correlation_id")
    except JournalValidationError as exc:
        raise JournalCorruptionError(str(exc), sequence=event.sequence) from exc
    if event.causation_id is not None and (
        not isinstance(event.causation_id, str)
        or not _EVENT_ID_RE.fullmatch(event.causation_id)
    ):
        raise JournalCorruptionError("Invalid causation ID", sequence=event.sequence)
    if event.source not in _ALLOWED_SOURCES:
        raise JournalCorruptionError("Invalid event source", sequence=event.sequence)
    if event.privacy not in {STANDARD_PRIVACY, PRIVATE_EPHEMERAL}:
        raise JournalCorruptionError("Invalid privacy mode", sequence=event.sequence)
    if event.outcome is not None and event.outcome not in _ALLOWED_OUTCOMES:
        raise JournalCorruptionError("Invalid event outcome", sequence=event.sequence)
    if event.privacy == PRIVATE_EPHEMERAL and event.payload:
        raise JournalCorruptionError(
            "Private-ephemeral event payload must be empty", sequence=event.sequence
        )
    try:
        _validate_payload(event.event_type, event.payload)
    except JournalValidationError as exc:
        raise JournalCorruptionError(str(exc), sequence=event.sequence) from exc
    if event.hash_algorithm not in {"sha256", "hmac-sha256"}:
        raise JournalCorruptionError("Invalid hash algorithm", sequence=event.sequence)
    for field_name, digest in (
        ("previous_hash", event.previous_hash),
        ("event_hash", event.event_hash),
    ):
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            raise JournalCorruptionError(
                f"Invalid {field_name}", sequence=event.sequence
            )


class EventJournal:
    """One bounded, append-only journal run."""

    def __init__(
        self,
        root: os.PathLike[str] | str,
        *,
        run_id: str | None = None,
        max_events: int = 100_000,
        max_event_bytes: int = 64 * 1024,
        lock_timeout_seconds: float = 1.0,
        wall_clock_ns: Callable[[], int] = time.time_ns,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
        id_factory: Callable[[], str] = lambda: secrets.token_hex(16),
        auth_key: bytes | None = None,
        create: bool = True,
    ) -> None:
        if isinstance(max_events, bool) or not isinstance(max_events, int) or max_events < 1:
            raise JournalValidationError("max_events must be a positive integer")
        if (
            isinstance(max_event_bytes, bool)
            or not isinstance(max_event_bytes, int)
            or max_event_bytes < 1_024
        ):
            raise JournalValidationError("max_event_bytes must be at least 1024")
        if not math.isfinite(float(lock_timeout_seconds)) or lock_timeout_seconds <= 0:
            raise JournalValidationError("lock timeout must be finite and positive")
        if auth_key is not None and not isinstance(auth_key, bytes):
            raise JournalValidationError("auth_key must be bytes")

        raw_root = Path(root).expanduser()
        if raw_root.exists() and raw_root.is_symlink():
            raise JournalValidationError("Journal root may not be a symlink")
        self.root = raw_root.resolve()
        self.runs_dir = (self.root / "runs").resolve(strict=False)
        if self.runs_dir.parent != self.root:
            raise JournalValidationError("Journal runs path escaped its root")

        self.max_events = max_events
        self.max_event_bytes = max_event_bytes
        self.lock_timeout_seconds = float(lock_timeout_seconds)
        self._wall_clock_ns = wall_clock_ns
        self._monotonic_ns = monotonic_ns
        self._id_factory = id_factory
        self._auth_key = auth_key
        self._session_started_ns = int(monotonic_ns())
        self.writer_id = self._new_event_id()
        self._failure_lock = threading.Lock()
        self._write_failures = 0

        if run_id is None:
            timestamp = int(wall_clock_ns())
            if timestamp < 0 or timestamp >= 10**20:
                raise JournalValidationError("Wall clock returned an unsupported timestamp")
            run_id = f"{timestamp:020d}-{self._new_event_id()}"
        if not isinstance(run_id, str) or not _RUN_ID_RE.fullmatch(run_id):
            raise JournalValidationError("Invalid journal run ID")
        self.run_id = run_id
        self.run_dir = (self.runs_dir / run_id).resolve(strict=False)
        self.events_dir = (self.run_dir / "events").resolve(strict=False)
        self._lock_file = (self.run_dir / ".append.lock").resolve(strict=False)
        if self.run_dir.parent != self.runs_dir or self.events_dir.parent != self.run_dir:
            raise JournalValidationError("Journal run path escaped its root")

        if create:
            self.root.mkdir(parents=True, exist_ok=True)
            self.runs_dir.mkdir(parents=True, exist_ok=True)
            if self.run_dir.exists() and self.run_dir.is_symlink():
                raise JournalValidationError("Journal run directory may not be a symlink")
            self.run_dir.mkdir(parents=True, exist_ok=True)
            if self.events_dir.exists() and self.events_dir.is_symlink():
                raise JournalValidationError("Journal events directory may not be a symlink")
            self.events_dir.mkdir(parents=True, exist_ok=True)
            self._ensure_lock_file()
        elif not self.events_dir.is_dir() or not self._lock_file.is_file():
            raise JournalIOError(f"Journal run does not exist: {run_id}")

        self._process_lock = _process_lock(self.run_dir)

    @property
    def write_failures(self) -> int:
        with self._failure_lock:
            return self._write_failures

    @property
    def hash_algorithm(self) -> str:
        return "hmac-sha256" if self._auth_key is not None else "sha256"

    def _new_event_id(self) -> str:
        value = str(self._id_factory())
        if not _EVENT_ID_RE.fullmatch(value):
            raise JournalValidationError("ID factory must return 32 lowercase hex characters")
        return value

    def _ensure_lock_file(self) -> None:
        fd = os.open(str(self._lock_file), os.O_CREAT | os.O_RDWR, 0o600)
        try:
            if os.fstat(fd).st_size == 0:
                os.write(fd, b"\0")
                os.fsync(fd)
        finally:
            os.close(fd)

    @contextmanager
    def _append_lock(self) -> Iterator[None]:
        with self._process_lock:
            deadline = time.monotonic() + self.lock_timeout_seconds
            stream = open(self._lock_file, "r+b", buffering=0)
            acquired = False
            try:
                if os.name == "nt":
                    import msvcrt

                    while not acquired:
                        try:
                            stream.seek(0)
                            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                            acquired = True
                        except OSError:
                            if time.monotonic() >= deadline:
                                raise JournalLockTimeout(
                                    "Timed out acquiring event-journal append lock"
                                )
                            time.sleep(0.005)
                else:
                    import fcntl

                    while not acquired:
                        try:
                            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                            acquired = True
                        except (BlockingIOError, OSError):
                            if time.monotonic() >= deadline:
                                raise JournalLockTimeout(
                                    "Timed out acquiring event-journal append lock"
                                )
                            time.sleep(0.005)
                yield
            finally:
                try:
                    if acquired:
                        if os.name == "nt":
                            import msvcrt

                            stream.seek(0)
                            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                        else:
                            import fcntl

                            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
                finally:
                    stream.close()

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        if os.name == "nt":
            return
        try:
            fd = os.open(str(directory), os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(fd)
        except OSError:
            pass
        finally:
            os.close(fd)

    def _event_paths(self) -> list[Path]:
        paths: list[tuple[int, Path]] = []
        try:
            entries = list(self.events_dir.iterdir())
        except OSError as exc:
            raise JournalIOError("Unable to enumerate journal events") from exc
        for path in entries:
            if path.name.startswith(".tmp-"):
                continue
            if path.is_symlink():
                raise JournalCorruptionError("Journal event may not be a symlink")
            match = _EVENT_FILENAME_RE.fullmatch(path.name)
            if match is None or not path.is_file():
                raise JournalCorruptionError(
                    f"Unexpected file in journal events directory: {path.name}"
                )
            paths.append((int(match.group("sequence")), path))
        paths.sort(key=lambda item: item[0])
        return [path for _, path in paths]

    def _read_path(self, path: Path) -> JournalEvent:
        match = _EVENT_FILENAME_RE.fullmatch(path.name)
        if match is None:
            raise JournalCorruptionError("Invalid journal event filename")
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise JournalIOError(f"Unable to read journal event {path.name}") from exc
        if len(raw) > self.max_event_bytes:
            raise JournalCorruptionError(
                "Journal event exceeds configured byte bound",
                sequence=int(match.group("sequence")),
            )
        try:
            value = json.loads(
                raw.decode("utf-8"), object_pairs_hook=_strict_json_object
            )
        except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateJSONKey) as exc:
            raise JournalCorruptionError(
                "Journal event is not valid UTF-8 JSON",
                sequence=int(match.group("sequence")),
            ) from exc
        if not isinstance(value, Mapping):
            raise JournalCorruptionError(
                "Journal event root must be an object",
                sequence=int(match.group("sequence")),
            )
        try:
            _validate_event_envelope_fields(value)
        except JournalCorruptionError as exc:
            raise JournalCorruptionError(
                str(exc), sequence=int(match.group("sequence"))
            ) from exc
        try:
            canonical = canonical_json_bytes(value)
        except JournalValidationError as exc:
            raise JournalCorruptionError(
                "Journal event is not canonical JSON",
                sequence=int(match.group("sequence")),
            ) from exc
        if raw != canonical:
            raise JournalCorruptionError(
                "Journal event bytes are not canonical JSON",
                sequence=int(match.group("sequence")),
            )
        try:
            event = JournalEvent.from_mapping(value)
        except JournalCorruptionError as exc:
            if exc.sequence is not None:
                raise
            raise JournalCorruptionError(
                str(exc), sequence=int(match.group("sequence"))
            ) from exc
        if event.sequence != int(match.group("sequence")) or event.event_id != match.group(
            "event_id"
        ):
            raise JournalCorruptionError(
                "Journal filename does not match its envelope", sequence=event.sequence
            )
        return event

    def _semantic_key(
        self,
        event_type: str,
        payload: Mapping[str, Any],
        context: JournalContext,
        outcome: str | None,
        causation_id: str | None,
    ) -> bytes:
        return canonical_json_bytes(
            {
                "event_type": event_type,
                "payload": payload,
                "trace_id": context.trace_id,
                "request_id": context.request_id,
                "correlation_id": context.correlation_id,
                "source": context.source,
                "privacy": (
                    PRIVATE_EPHEMERAL
                    if context.private_ephemeral
                    else STANDARD_PRIVACY
                ),
                "outcome": outcome,
                "causation_id": causation_id,
            }
        )

    def append(
        self,
        event_type: str,
        payload: Mapping[str, Any] | None = None,
        *,
        context: JournalContext | None = None,
        outcome: str | None = None,
        causation_id: str | None = None,
        event_id: str | None = None,
    ) -> JournalEvent:
        """Append one durable event or raise a typed error.

        Private-ephemeral context is enforced here, not at call sites: every
        supplied payload is discarded before validation or serialization.
        """

        if not isinstance(event_type, str) or not _KIND_RE.fullmatch(event_type):
            raise JournalValidationError("Invalid event type")
        context = context or JournalContext()
        source = str(context.source or "unknown").lower()
        if source not in _ALLOWED_SOURCES:
            raise JournalValidationError("Invalid journal source")
        context = JournalContext(
            correlation_id=_validate_identifier(
                context.correlation_id, "correlation_id"
            ),
            trace_id=_validate_identifier(context.trace_id, "trace_id"),
            request_id=_validate_identifier(context.request_id, "request_id"),
            source=source,
            private_ephemeral=bool(context.private_ephemeral),
        )
        if outcome is not None and outcome not in _ALLOWED_OUTCOMES:
            raise JournalValidationError("Invalid event outcome")
        if causation_id is not None and not _EVENT_ID_RE.fullmatch(causation_id):
            raise JournalValidationError("Invalid causation ID")
        if event_id is None:
            event_id = self._new_event_id()
        elif not isinstance(event_id, str) or not _EVENT_ID_RE.fullmatch(event_id):
            raise JournalValidationError("Invalid event ID")

        privacy = PRIVATE_EPHEMERAL if context.private_ephemeral else STANDARD_PRIVACY
        normalized_payload = (
            {} if context.private_ephemeral else _validate_payload(event_type, payload or {})
        )
        semantic_key = self._semantic_key(
            event_type, normalized_payload, context, outcome, causation_id
        )

        try:
            with self._append_lock():
                paths = self._event_paths()
                existing_paths = [
                    path
                    for path in paths
                    if path.name.endswith(f"-{event_id}.json")
                ]
                if existing_paths:
                    if len(existing_paths) != 1:
                        raise JournalCorruptionError(
                            "Event ID occurs more than once in the journal"
                        )
                    # An idempotent retry is a read of committed state, not a
                    # shortcut around verification. Validate the complete
                    # sequence/predecessor chain and the configured SHA/HMAC
                    # before treating an existing event as successful.
                    for _ in self.iter_events(verify=True):
                        pass
                    existing = self._read_path(existing_paths[0])
                    existing_key = self._semantic_key(
                        existing.event_type,
                        existing.payload,
                        JournalContext(
                            correlation_id=existing.correlation_id,
                            trace_id=existing.trace_id,
                            request_id=existing.request_id,
                            source=existing.source,
                            private_ephemeral=(
                                existing.privacy == PRIVATE_EPHEMERAL
                            ),
                        ),
                        existing.outcome,
                        existing.causation_id,
                    )
                    if hmac.compare_digest(existing_key, semantic_key):
                        return existing
                    raise EventConflict("Event ID already exists with different data")

                if len(paths) >= self.max_events:
                    raise JournalFull(
                        f"Journal run reached max_events={self.max_events}"
                    )
                if paths:
                    previous = self._read_path(paths[-1])
                    expected_previous = compute_event_hash(
                        previous.as_dict(), self._auth_key
                    )
                    if not hmac.compare_digest(previous.event_hash, expected_previous):
                        raise JournalCorruptionError(
                            "Journal head hash is invalid", sequence=previous.sequence
                        )
                    sequence = previous.sequence + 1
                    previous_hash = previous.event_hash
                else:
                    sequence = 1
                    previous_hash = GENESIS_HASH

                occurred_at_ns = int(self._wall_clock_ns())
                monotonic_ns = max(
                    0, int(self._monotonic_ns()) - self._session_started_ns
                )
                if occurred_at_ns < 0:
                    raise JournalValidationError("Wall clock returned a negative timestamp")
                envelope: dict[str, Any] = {
                    "schema": SCHEMA_VERSION,
                    "sequence": sequence,
                    "event_id": event_id,
                    "event_type": event_type,
                    "kind_version": KIND_VERSION,
                    "occurred_at_ns": occurred_at_ns,
                    "writer_id": self.writer_id,
                    "monotonic_ns": monotonic_ns,
                    "trace_id": context.trace_id,
                    "request_id": context.request_id,
                    "correlation_id": context.correlation_id,
                    "causation_id": causation_id,
                    "source": source,
                    "privacy": privacy,
                    "outcome": outcome,
                    "payload": normalized_payload,
                    "previous_hash": previous_hash,
                    "hash_algorithm": self.hash_algorithm,
                }
                envelope["event_hash"] = compute_event_hash(envelope, self._auth_key)
                serialized = canonical_json_bytes(envelope)
                if len(serialized) > self.max_event_bytes:
                    raise JournalValidationError("Serialized journal event is too large")

                final_path = self.events_dir / f"{sequence:020d}-{event_id}.json"
                temp_path = self.events_dir / (
                    f".tmp-{sequence:020d}-{event_id}-{secrets.token_hex(16)}"
                )
                fd: int | None = None
                try:
                    fd = os.open(
                        str(temp_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
                    )
                    with os.fdopen(fd, "wb") as stream:
                        fd = None
                        stream.write(serialized)
                        stream.flush()
                        os.fsync(stream.fileno())
                    if final_path.exists():
                        raise JournalCorruptionError(
                            "Target journal sequence already exists", sequence=sequence
                        )
                    os.replace(temp_path, final_path)
                    self._fsync_directory(self.events_dir)
                finally:
                    if fd is not None:
                        os.close(fd)
                    try:
                        temp_path.unlink()
                    except FileNotFoundError:
                        pass
                return JournalEvent.from_mapping(envelope)
        except EventJournalError:
            raise
        except OSError as exc:
            raise JournalIOError("Unable to append event journal record") from exc

    def append_safe(self, *args, **kwargs) -> JournalEvent | None:
        """Fail-open append used by runtime observability hooks."""

        try:
            return self.append(*args, **kwargs)
        except Exception:
            with self._failure_lock:
                self._write_failures += 1
            logger.warning("Event journal append failed", exc_info=True)
            return None

    def iter_events(self, *, verify: bool = True) -> Iterator[JournalEvent]:
        expected_sequence = 1
        previous_hash = GENESIS_HASH
        for path in self._event_paths():
            event = self._read_path(path)
            if event.sequence != expected_sequence:
                raise JournalCorruptionError(
                    f"Journal sequence gap: expected {expected_sequence}, got {event.sequence}",
                    sequence=event.sequence,
                )
            if verify:
                if event.hash_algorithm != self.hash_algorithm:
                    raise JournalCorruptionError(
                        "Journal hash algorithm does not match this reader",
                        sequence=event.sequence,
                    )
                if not hmac.compare_digest(event.previous_hash, previous_hash):
                    raise JournalCorruptionError(
                        "Journal previous-hash chain is broken",
                        sequence=event.sequence,
                    )
                expected_hash = compute_event_hash(event.as_dict(), self._auth_key)
                if not hmac.compare_digest(event.event_hash, expected_hash):
                    raise JournalCorruptionError(
                        "Journal event hash is invalid", sequence=event.sequence
                    )
            yield event
            previous_hash = event.event_hash
            expected_sequence += 1

    def verify(self) -> VerificationReport:
        count = 0
        first: int | None = None
        last: int | None = None
        head = GENESIS_HASH
        try:
            for event in self.iter_events(verify=True):
                count += 1
                first = event.sequence if first is None else first
                last = event.sequence
                head = event.event_hash
        except EventJournalError as exc:
            return VerificationReport(
                valid=False,
                event_count=count,
                first_sequence=first,
                last_sequence=last,
                head_hash=head,
                error=str(exc),
                corrupt_sequence=getattr(exc, "sequence", None),
            )
        return VerificationReport(
            valid=True,
            event_count=count,
            first_sequence=first,
            last_sequence=last,
            head_hash=head,
        )

    def recover(self, *, remove_orphan_temps: bool = False) -> RecoveryReport:
        """Inspect crash leftovers without ever hiding committed corruption."""

        try:
            temps = [
                path
                for path in self.events_dir.iterdir()
                if path.name.startswith(".tmp-") and path.is_file()
            ]
        except OSError as exc:
            raise JournalIOError("Unable to inspect journal recovery state") from exc
        removed = 0
        if remove_orphan_temps:
            with self._append_lock():
                for path in temps:
                    try:
                        path.unlink()
                        removed += 1
                    except FileNotFoundError:
                        pass
                    except OSError as exc:
                        raise JournalIOError("Unable to remove orphan journal temp") from exc
                if removed:
                    self._fsync_directory(self.events_dir)
        report = self.verify()
        return RecoveryReport(
            valid_events=report.event_count,
            orphan_temps=len(temps),
            removed_temps=removed,
            corruption=None if report.valid else report.error,
        )

    @classmethod
    def list_run_ids(cls, root: os.PathLike[str] | str) -> tuple[str, ...]:
        runs_dir = Path(root).expanduser().resolve() / "runs"
        if not runs_dir.exists():
            return ()
        run_ids: list[str] = []
        for path in runs_dir.iterdir():
            if path.is_symlink() or not path.is_dir() or not _RUN_ID_RE.fullmatch(path.name):
                raise JournalCorruptionError(
                    f"Unexpected entry in journal runs directory: {path.name}"
                )
            events_dir = path / "events"
            lock_file = path / ".append.lock"
            if events_dir.is_symlink() or lock_file.is_symlink():
                raise JournalCorruptionError(
                    f"Journal run contains a symlinked control path: {path.name}"
                )
            complete = events_dir.is_dir() and lock_file.is_file()
            if complete:
                try:
                    # _ensure_lock_file writes and fsyncs this byte last, so a
                    # zero-length lock file is still an unpublished residue.
                    complete = lock_file.stat().st_size >= 1
                except OSError:
                    complete = False
            if not complete:
                try:
                    has_committed_events = events_dir.is_dir() and any(
                        entry.name.endswith(".json")
                        for entry in events_dir.iterdir()
                    )
                except OSError as exc:
                    raise JournalCorruptionError(
                        f"Unable to inspect incomplete journal run: {path.name}"
                    ) from exc
                if has_committed_events:
                    # Avoid a false corruption report if list_run_ids raced
                    # the final fsync byte of a legitimately published run.
                    try:
                        published_now = (
                            not events_dir.is_symlink()
                            and not lock_file.is_symlink()
                            and events_dir.is_dir()
                            and lock_file.is_file()
                            and lock_file.stat().st_size >= 1
                        )
                    except OSError:
                        published_now = False
                    if published_now:
                        run_ids.append(path.name)
                        continue
                    # Missing/truncated control state on a run that already
                    # published events is corruption, not a harmless creation
                    # residue. Never hide those records from whole-root replay.
                    raise JournalCorruptionError(
                        f"Incomplete journal run contains committed events: {path.name}"
                    )
                # A process can stop after creating the run directory but
                # before publishing its control files. Such a validly named
                # residue is not a committed run and must not make replay of
                # every older, complete run unavailable.
                logger.warning("Skipping incomplete journal run %s", path.name)
                continue
            run_ids.append(path.name)
        return tuple(sorted(run_ids))


class RotatingEventJournal:
    """Thread-safe writer that starts a fresh immutable run at its hard bound.

    Rotation never edits or deletes an older run.  It only swaps the active
    writer after ``JournalFull`` and retries the event once, so a long-lived
    brain process does not silently lose all later observability.
    """

    def __init__(self, root: os.PathLike[str] | str, **journal_options) -> None:
        if "run_id" in journal_options:
            raise JournalValidationError(
                "RotatingEventJournal manages run_id automatically"
            )
        self.root = Path(root).expanduser().resolve()
        self._journal_options = dict(journal_options)
        self._soft_max_events = int(
            self._journal_options.pop("max_events", 100_000)
        )
        if self._soft_max_events < 1:
            raise JournalValidationError("max_events must be a positive integer")
        # Leave bounded headroom so an interaction/tick accepted just before
        # the soft boundary can finish in the same run. Rotation is performed
        # only at the next root event, never between its LLM, tool, state-delta,
        # and terminal events.
        self._continuation_reserve = max(
            64, min(1_024, self._soft_max_events)
        )
        self._lock = threading.RLock()
        self._write_failures = 0
        self._current_event_count = 0
        self._current = self._new_run()

    def _new_run(self) -> EventJournal:
        return EventJournal(
            self.root,
            max_events=self._soft_max_events + self._continuation_reserve,
            **self._journal_options,
        )

    def _rotate(self) -> None:
        self._current = self._new_run()
        self._current_event_count = 0
        started = self._current.append(
            "journal.run_started",
            {"format": "atomic-json-v1"},
            context=JournalContext(source="system"),
            outcome="started",
        )
        self._current_event_count = started.sequence

    @property
    def run_id(self) -> str:
        with self._lock:
            return self._current.run_id

    @property
    def writer_id(self) -> str:
        with self._lock:
            return self._current.writer_id

    @property
    def write_failures(self) -> int:
        with self._lock:
            return self._write_failures

    def append(self, *args, **kwargs) -> JournalEvent:
        with self._lock:
            event_type = args[0] if args else kwargs.get("event_type")
            if (
                event_type
                in {
                    "interaction.accepted",
                    "cognitive_tick.started",
                    "delivery.durable",
                    "delivery.acked",
                }
                and self._current_event_count >= self._soft_max_events
            ):
                self._rotate()
            try:
                event = self._current.append(*args, **kwargs)
            except JournalFull:
                # Emergency rotation is reachable only if a single root span
                # emits more than the reserved continuation allowance.
                self._rotate()
                event = self._current.append(*args, **kwargs)
            self._current_event_count = max(
                self._current_event_count, event.sequence
            )
            return event

    def append_safe(self, *args, **kwargs) -> JournalEvent | None:
        try:
            return self.append(*args, **kwargs)
        except Exception:
            with self._lock:
                self._write_failures += 1
            logger.warning("Rotating event journal append failed", exc_info=True)
            return None

    def append_pinned(self, *args, **kwargs) -> tuple[EventJournal, JournalEvent]:
        """Append and atomically return the concrete run that owns the event.

        Callers that create a multi-event span can retain the returned
        ``EventJournal`` so later child/terminal events cannot be moved into a
        newer run by an unrelated concurrent root event.
        """

        with self._lock:
            event = self.append(*args, **kwargs)
            return self._current, event

    def append_pinned_safe(
        self, *args, **kwargs
    ) -> tuple[EventJournal, JournalEvent] | None:
        """Fail-open variant of :meth:`append_pinned`."""

        try:
            return self.append_pinned(*args, **kwargs)
        except Exception:
            with self._lock:
                self._write_failures += 1
            logger.warning("Rotating event journal append failed", exc_info=True)
            return None

    def verify_current_run(self) -> VerificationReport:
        with self._lock:
            return self._current.verify()


def activate_journal_context(
    journal: EventJournal,
    context: JournalContext,
    *,
    causation_id: str | None = None,
) -> contextvars.Token:
    """Activate a request-local journal context in the current execution flow."""

    return _ACTIVE_CONTEXT.set(
        ActiveJournalContext(
            journal=journal,
            context=context,
            last_event_id=causation_id,
        )
    )


def reset_journal_context(token: contextvars.Token) -> None:
    _ACTIVE_CONTEXT.reset(token)


@contextmanager
def journal_context(
    journal: EventJournal,
    context: JournalContext,
    *,
    causation_id: str | None = None,
) -> Iterator[ActiveJournalContext]:
    token = activate_journal_context(journal, context, causation_id=causation_id)
    try:
        active = _ACTIVE_CONTEXT.get()
        assert active is not None
        yield active
    finally:
        reset_journal_context(token)


def current_journal_context() -> ActiveJournalContext | None:
    return _ACTIVE_CONTEXT.get()


def record_current_event(
    event_type: str,
    payload: Mapping[str, Any] | None = None,
    *,
    outcome: str | None = None,
) -> JournalEvent | None:
    """Append through the active request scope, preserving causal order."""

    active = _ACTIVE_CONTEXT.get()
    if active is None:
        return None
    event = active.journal.append_safe(
        event_type,
        payload,
        context=active.context,
        outcome=outcome,
        causation_id=active.last_event_id,
    )
    if event is not None:
        active.last_event_id = event.event_id
    return event


def detach_current_event_head() -> str | None:
    """Return the active causal head before a request scope is reset."""

    active = _ACTIVE_CONTEXT.get()
    return None if active is None else active.last_event_id


__all__ = [
    "ActiveJournalContext",
    "EventConflict",
    "EventJournal",
    "EventJournalError",
    "GENESIS_HASH",
    "JournalContext",
    "JournalCorruptionError",
    "JournalEvent",
    "JournalFull",
    "JournalIOError",
    "JournalLockTimeout",
    "JournalValidationError",
    "PRIVATE_EPHEMERAL",
    "RecoveryReport",
    "RotatingEventJournal",
    "SCHEMA_VERSION",
    "VerificationReport",
    "activate_journal_context",
    "canonical_json_bytes",
    "compute_event_hash",
    "current_journal_context",
    "detach_current_event_head",
    "journal_context",
    "record_current_event",
    "reset_journal_context",
]
