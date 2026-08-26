"""Durable, idempotent operation plans for recoverable Aura workflows.

The ledger stores an immutable canonical JSON plan before a workflow performs
external writes.  A caller then advances ``planned -> applying -> committed``
with compare-and-swap (CAS).  An ``applying`` operation is intentionally left
recoverable after a transient failure because an external write may already
have happened.

The SHA-256 digest covers schema version, operation identity, operation type,
and the plan.  It detects accidental/on-disk payload corruption; it is not an
authentication mechanism against a hostile writer that can recompute hashes.
Status and revision are protected by SQLite constraints and atomic CAS, not by
the immutable-plan digest.  Aura's process-wide writer lease remains the
runtime ownership boundary; this class additionally serializes its connection
for safe use by multiple threads.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Final

from config import Config


SCHEMA_VERSION: Final[int] = 1
MAX_PLAN_BYTES: Final[int] = 256 * 1024
MAX_PLAN_DEPTH: Final[int] = 32
MAX_PLAN_ITEMS: Final[int] = 10_000
MAX_PLAN_KEY_BYTES: Final[int] = 1_024
MAX_PLAN_STRING_BYTES: Final[int] = 128 * 1024
MAX_IDENTIFIER_LENGTH: Final[int] = 128
DEFAULT_BUSY_TIMEOUT_MS: Final[int] = 5_000
DEFAULT_RECOVERY_LIMIT: Final[int] = 1_000
RECOVERY_SCAN_BATCH: Final[int] = 256
SQLITE_MAX_INTEGER: Final[int] = 2**63 - 1

_IDENTIFIER_RE = re.compile(
    rf"\A[A-Za-z0-9][A-Za-z0-9_.:@+-]{{0,{MAX_IDENTIFIER_LENGTH - 1}}}\Z"
)
_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")


class OperationLedgerError(RuntimeError):
    """Base error for the operation ledger."""


class OperationValidationError(OperationLedgerError, ValueError):
    """Raised before persistence when an argument is not safely encodable."""


class OperationConflictError(OperationLedgerError):
    """An operation ID already names a different immutable plan."""


class OperationCorruptionError(OperationLedgerError):
    """A persisted record failed structural or digest validation."""


class OperationNotFoundError(OperationLedgerError, LookupError):
    """The requested operation does not exist."""


class OperationPreconditionError(OperationLedgerError):
    """A requested state transition is not part of the ledger protocol."""


class OperationLedgerIOError(OperationLedgerError):
    """SQLite could not complete a ledger operation."""


class OperationLedgerClosedError(OperationLedgerError):
    """The ledger connection has already been closed."""


class OperationStatus(str, Enum):
    PLANNED = "planned"
    APPLYING = "applying"
    COMMITTED = "committed"
    QUARANTINED = "quarantined"


class QuarantineReason(str, Enum):
    CORRUPTION = "corruption"
    PRECONDITION_MISMATCH = "precondition_mismatch"


_RECOVERABLE_STATUSES: Final[tuple[str, ...]] = (
    OperationStatus.PLANNED.value,
    OperationStatus.APPLYING.value,
)
_TERMINAL_STATUSES: Final[tuple[str, ...]] = (
    OperationStatus.COMMITTED.value,
    OperationStatus.QUARANTINED.value,
)
_ALLOWED_TRANSITIONS: Final[set[tuple[str, str]]] = {
    (OperationStatus.PLANNED.value, OperationStatus.APPLYING.value),
    (OperationStatus.APPLYING.value, OperationStatus.COMMITTED.value),
}


@dataclass(frozen=True, slots=True)
class OperationRecord:
    """A validated detached snapshot of one operation row."""

    schema_version: int
    op_id: str
    op_type: str
    status: OperationStatus
    revision: int
    plan: dict[str, Any]
    plan_json: str
    plan_sha256: str
    created_at_ns: int
    updated_at_ns: int
    quarantine_reason: QuarantineReason | None = None


@dataclass(frozen=True, slots=True)
class CheckpointResult:
    """SQLite WAL checkpoint counters."""

    busy: int
    log_frames: int
    checkpointed_frames: int


class _DuplicateJSONKey(ValueError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise _DuplicateJSONKey(key)
        value[key] = item
    return value


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def _validate_identifier(value: object, field: str) -> str:
    if type(value) is not str or not _IDENTIFIER_RE.fullmatch(value):
        raise OperationValidationError(f"{field} is not a safe identifier")
    return value


def _validate_nonnegative_int(value: object, field: str) -> int:
    if type(value) is not int or value < 0 or value > SQLITE_MAX_INTEGER:
        raise OperationValidationError(
            f"{field} must be a SQLite-range non-negative integer "
            "(bool is not accepted)"
        )
    return value


def _validate_positive_int(value: object, field: str) -> int:
    if type(value) is not int or value <= 0 or value > SQLITE_MAX_INTEGER:
        raise OperationValidationError(
            f"{field} must be a SQLite-range positive integer "
            "(bool is not accepted)"
        )
    return value


def _next_timestamp_ns(previous: int | None = None) -> int:
    """Return an in-range timestamp that moves forward within one operation."""

    now = time.time_ns()
    if type(now) is not int or now < 0 or now >= SQLITE_MAX_INTEGER:
        raise OperationLedgerIOError("system clock is outside SQLite range")
    if previous is None:
        return now
    if type(previous) is not int or previous < 0 or previous > SQLITE_MAX_INTEGER:
        raise OperationCorruptionError("operation timestamp is corrupt")
    if previous == SQLITE_MAX_INTEGER:
        raise OperationCorruptionError("operation timestamp cannot advance")
    return max(now, previous + 1)


def _clone_json_value(
    value: object,
    *,
    depth: int,
    budget: list[int],
    location: str,
) -> Any:
    if depth > MAX_PLAN_DEPTH:
        raise OperationValidationError(
            f"plan exceeds maximum depth {MAX_PLAN_DEPTH}"
        )

    budget[0] += 1
    if budget[0] > MAX_PLAN_ITEMS:
        raise OperationValidationError(
            f"plan exceeds maximum item count {MAX_PLAN_ITEMS}"
        )

    if value is None or type(value) is bool:
        return value
    if type(value) is int:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise OperationValidationError(f"{location} must be finite")
        return value
    if type(value) is str:
        if len(value.encode("utf-8", errors="surrogatepass")) > MAX_PLAN_STRING_BYTES:
            raise OperationValidationError(
                f"{location} exceeds maximum string size"
            )
        return value
    if type(value) is list:
        return [
            _clone_json_value(
                item,
                depth=depth + 1,
                budget=budget,
                location=f"{location}[{index}]",
            )
            for index, item in enumerate(value)
        ]
    if type(value) is dict:
        clone: dict[str, Any] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise OperationValidationError(
                    f"{location} contains a non-string object key"
                )
            if len(key.encode("utf-8", errors="surrogatepass")) > MAX_PLAN_KEY_BYTES:
                raise OperationValidationError(
                    f"{location} contains an oversized object key"
                )
            clone[key] = _clone_json_value(
                item,
                depth=depth + 1,
                budget=budget,
                location=f"{location}.{key}",
            )
        return clone
    raise OperationValidationError(
        f"{location} contains unsupported type {type(value).__name__}"
    )


def canonical_plan_json(plan: object) -> tuple[dict[str, Any], str]:
    """Return a detached plan and its deterministic JSON representation."""

    if type(plan) is not dict:
        raise OperationValidationError("operation plan must be a JSON object")
    clone = _clone_json_value(
        plan,
        depth=0,
        budget=[0],
        location="plan",
    )
    try:
        text = json.dumps(
            clone,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise OperationValidationError("operation plan is not canonical JSON") from exc
    if len(text.encode("utf-8")) > MAX_PLAN_BYTES:
        raise OperationValidationError(
            f"operation plan exceeds maximum size {MAX_PLAN_BYTES} bytes"
        )
    return clone, text


def _plan_digest(op_id: str, op_type: str, plan: dict[str, Any]) -> str:
    envelope = {
        "op_id": op_id,
        "op_type": op_type,
        "plan": plan,
        "schema_version": SCHEMA_VERSION,
    }
    encoded = json.dumps(
        envelope,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _coerce_status(value: object, field: str) -> OperationStatus:
    if isinstance(value, OperationStatus):
        return value
    if type(value) is not str:
        raise OperationValidationError(f"{field} must be an operation status")
    try:
        return OperationStatus(value)
    except ValueError as exc:
        raise OperationValidationError(
            f"{field} must be an operation status"
        ) from exc


def _coerce_quarantine_reason(value: object) -> QuarantineReason:
    if isinstance(value, QuarantineReason):
        return value
    if type(value) is not str:
        raise OperationValidationError("reason must be a quarantine reason")
    try:
        return QuarantineReason(value)
    except ValueError as exc:
        raise OperationValidationError(
            "reason must be corruption or precondition_mismatch"
        ) from exc


class OperationLedger:
    """SQLite-backed immutable-plan ledger with atomic status transitions."""

    def __init__(
        self,
        path: os.PathLike[str] | str | None = None,
        *,
        busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
    ):
        busy_timeout_ms = _validate_positive_int(
            busy_timeout_ms,
            "busy_timeout_ms",
        )
        configured_path = Config.OPERATION_LEDGER_FILE if path is None else path
        try:
            raw_path = os.fspath(configured_path)
        except TypeError as exc:
            raise OperationValidationError("ledger path must be path-like") from exc
        if type(raw_path) is not str or not raw_path or "\x00" in raw_path:
            raise OperationValidationError("ledger path is invalid")

        self.path = Path(os.path.abspath(raw_path))
        self._lock = threading.RLock()
        self._connection: sqlite3.Connection | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists() and self.path.is_dir():
                raise OperationValidationError("ledger path names a directory")
            if self.path.is_symlink():
                raise OperationValidationError("ledger path must not be a symlink")
            connection = sqlite3.connect(
                os.fspath(self.path),
                timeout=busy_timeout_ms / 1000.0,
                isolation_level=None,
                check_same_thread=False,
            )
            connection.row_factory = sqlite3.Row
            self._connection = connection
            self._configure_connection(busy_timeout_ms)
            self._initialize_schema()
        except OperationLedgerError:
            self._close_after_init_failure()
            raise
        except (OSError, sqlite3.DatabaseError) as exc:
            self._close_after_init_failure()
            raise OperationLedgerIOError("could not initialize operation ledger") from exc

    def _close_after_init_failure(self) -> None:
        connection = self._connection
        self._connection = None
        if connection is not None:
            try:
                connection.close()
            except sqlite3.DatabaseError:
                pass

    def _require_connection(self) -> sqlite3.Connection:
        connection = self._connection
        if connection is None:
            raise OperationLedgerClosedError("operation ledger is closed")
        return connection

    def _configure_connection(self, busy_timeout_ms: int) -> None:
        connection = self._require_connection()
        journal_mode = connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]
        if str(journal_mode).lower() != "wal":
            raise OperationLedgerIOError("operation ledger could not enable WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA trusted_schema=OFF")

    def _initialize_schema(self) -> None:
        connection = self._require_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if type(version) is not int or version not in (0, SCHEMA_VERSION):
                raise OperationCorruptionError(
                    "unsupported operation ledger schema version"
                )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS operations (
                    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
                    op_id TEXT PRIMARY KEY NOT NULL,
                    op_type TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (
                        status IN ('planned', 'applying', 'committed', 'quarantined')
                    ),
                    revision INTEGER NOT NULL CHECK (
                        typeof(revision) = 'integer' AND revision >= 0
                    ),
                    plan_json TEXT NOT NULL,
                    plan_sha256 TEXT NOT NULL CHECK (
                        typeof(plan_sha256) = 'text' AND length(plan_sha256) = 64
                    ),
                    quarantine_reason TEXT CHECK (
                        quarantine_reason IS NULL OR quarantine_reason IN (
                            'corruption', 'precondition_mismatch'
                        )
                    ),
                    created_at_ns INTEGER NOT NULL CHECK (
                        typeof(created_at_ns) = 'integer' AND created_at_ns >= 0
                    ),
                    updated_at_ns INTEGER NOT NULL CHECK (
                        typeof(updated_at_ns) = 'integer' AND
                        updated_at_ns >= created_at_ns
                    )
                ) STRICT
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_operations_status_created
                ON operations(status, created_at_ns, op_id)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_operations_type_status_created
                ON operations(op_type, status, created_at_ns, op_id)
                """
            )
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(operations)")
            }
            required = {
                "schema_version",
                "op_id",
                "op_type",
                "status",
                "revision",
                "plan_json",
                "plan_sha256",
                "quarantine_reason",
                "created_at_ns",
                "updated_at_ns",
            }
            if not required.issubset(columns):
                raise OperationCorruptionError(
                    "operation ledger schema is missing required columns"
                )
            if version == 0:
                connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            connection.execute("COMMIT")
        except BaseException:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.DatabaseError:
                pass
            raise

    def _run_write(self, callback):
        connection = self._require_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            result = callback(connection)
            connection.execute("COMMIT")
            return result
        except BaseException as exc:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.DatabaseError:
                pass
            if isinstance(exc, OperationLedgerError):
                raise
            if isinstance(exc, sqlite3.DatabaseError):
                raise OperationLedgerIOError(
                    "operation ledger write failed"
                ) from exc
            raise

    @staticmethod
    def _decode_record(row: sqlite3.Row) -> OperationRecord:
        op_id = row["op_id"]
        try:
            _validate_identifier(op_id, "persisted op_id")
            op_type = _validate_identifier(row["op_type"], "persisted op_type")
        except OperationValidationError as exc:
            raise OperationCorruptionError(
                "operation identity is corrupt"
            ) from exc

        schema_version = row["schema_version"]
        revision = row["revision"]
        created_at_ns = row["created_at_ns"]
        updated_at_ns = row["updated_at_ns"]
        if type(schema_version) is not int or schema_version != SCHEMA_VERSION:
            raise OperationCorruptionError(f"operation {op_id} has invalid schema")
        if (
            type(revision) is not int
            or revision < 0
            or revision >= SQLITE_MAX_INTEGER
        ):
            raise OperationCorruptionError(f"operation {op_id} has invalid revision")
        if (
            type(created_at_ns) is not int
            or created_at_ns < 0
            or type(updated_at_ns) is not int
            or updated_at_ns < created_at_ns
            or updated_at_ns >= SQLITE_MAX_INTEGER
        ):
            raise OperationCorruptionError(f"operation {op_id} has invalid timestamps")

        try:
            status = OperationStatus(row["status"])
        except (TypeError, ValueError) as exc:
            raise OperationCorruptionError(
                f"operation {op_id} has invalid status"
            ) from exc

        raw_reason = row["quarantine_reason"]
        if raw_reason is None:
            reason = None
        else:
            try:
                reason = QuarantineReason(raw_reason)
            except (TypeError, ValueError) as exc:
                raise OperationCorruptionError(
                    f"operation {op_id} has invalid quarantine reason"
                ) from exc
        if status is OperationStatus.QUARANTINED and reason is None:
            raise OperationCorruptionError(
                f"operation {op_id} is quarantined without a reason"
            )
        if status is not OperationStatus.QUARANTINED and reason is not None:
            raise OperationCorruptionError(
                f"operation {op_id} has an unexpected quarantine reason"
            )

        plan_json = row["plan_json"]
        plan_sha256 = row["plan_sha256"]
        try:
            if type(plan_json) is not str or type(plan_sha256) is not str:
                raise ValueError("plan fields must be text")
            if not _SHA256_RE.fullmatch(plan_sha256):
                raise ValueError("hash is not lowercase SHA-256")
            if len(plan_json.encode("utf-8")) > MAX_PLAN_BYTES:
                raise ValueError("plan is oversized")
            decoded = json.loads(
                plan_json,
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_json_constant,
            )
            plan, canonical = canonical_plan_json(decoded)
        except (
            ValueError,
            TypeError,
            OverflowError,
            RecursionError,
            UnicodeError,
            OperationLedgerError,
        ) as exc:
            raise OperationCorruptionError(
                f"operation {op_id} plan cannot be decoded"
            ) from exc
        if not hmac.compare_digest(
            plan_json.encode("utf-8"),
            canonical.encode("utf-8"),
        ):
            raise OperationCorruptionError(
                f"operation {op_id} plan is not canonical"
            )
        expected_hash = _plan_digest(op_id, op_type, plan)
        if not hmac.compare_digest(plan_sha256, expected_hash):
            raise OperationCorruptionError(
                f"operation {op_id} plan hash does not match"
            )
        return OperationRecord(
            schema_version=schema_version,
            op_id=op_id,
            op_type=op_type,
            status=status,
            revision=revision,
            plan=plan,
            plan_json=plan_json,
            plan_sha256=plan_sha256,
            created_at_ns=created_at_ns,
            updated_at_ns=updated_at_ns,
            quarantine_reason=reason,
        )

    def create_or_get_plan(
        self,
        op_id: str,
        op_type: str,
        plan: object,
    ) -> OperationRecord:
        """Create a plan once, or return the exact existing immutable plan."""

        op_id = _validate_identifier(op_id, "op_id")
        op_type = _validate_identifier(op_type, "op_type")
        detached_plan, plan_json = canonical_plan_json(plan)
        plan_sha256 = _plan_digest(op_id, op_type, detached_plan)

        with self._lock:
            def create(connection: sqlite3.Connection) -> OperationRecord:
                row = connection.execute(
                    "SELECT * FROM operations WHERE op_id = ?",
                    (op_id,),
                ).fetchone()
                if row is not None:
                    record = self._decode_record(row)
                    if (
                        record.op_type != op_type
                        or not hmac.compare_digest(
                            record.plan_sha256,
                            plan_sha256,
                        )
                        or not hmac.compare_digest(
                            record.plan_json.encode("utf-8"),
                            plan_json.encode("utf-8"),
                        )
                    ):
                        raise OperationConflictError(
                            f"operation {op_id} already has a different plan"
                        )
                    return record

                created_at_ns = _next_timestamp_ns()
                connection.execute(
                    """
                    INSERT INTO operations (
                        schema_version, op_id, op_type, status, revision,
                        plan_json, plan_sha256, quarantine_reason,
                        created_at_ns, updated_at_ns
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
                    """,
                    (
                        SCHEMA_VERSION,
                        op_id,
                        op_type,
                        OperationStatus.PLANNED.value,
                        0,
                        plan_json,
                        plan_sha256,
                        created_at_ns,
                        created_at_ns,
                    ),
                )
                inserted = connection.execute(
                    "SELECT * FROM operations WHERE op_id = ?",
                    (op_id,),
                ).fetchone()
                if inserted is None:
                    raise OperationLedgerIOError(
                        "operation insert did not produce a row"
                    )
                return self._decode_record(inserted)

            return self._run_write(create)

    def get(self, op_id: str) -> OperationRecord | None:
        """Return a fully validated record, or ``None`` if it does not exist."""

        op_id = _validate_identifier(op_id, "op_id")
        with self._lock:
            connection = self._require_connection()
            try:
                row = connection.execute(
                    "SELECT * FROM operations WHERE op_id = ?",
                    (op_id,),
                ).fetchone()
            except sqlite3.DatabaseError as exc:
                raise OperationLedgerIOError("operation ledger read failed") from exc
            return None if row is None else self._decode_record(row)

    def compare_and_swap(
        self,
        op_id: str,
        *,
        expected_revision: int,
        expected_status: OperationStatus | str,
        new_status: OperationStatus | str,
    ) -> bool:
        """Atomically advance one legal transition; return False if stale."""

        op_id = _validate_identifier(op_id, "op_id")
        expected_revision = _validate_nonnegative_int(
            expected_revision,
            "expected_revision",
        )
        expected = _coerce_status(expected_status, "expected_status")
        target = _coerce_status(new_status, "new_status")
        if (expected.value, target.value) not in _ALLOWED_TRANSITIONS:
            raise OperationPreconditionError(
                f"illegal operation transition {expected.value}->{target.value}"
            )

        with self._lock:
            def update(connection: sqlite3.Connection) -> bool:
                row = connection.execute(
                    "SELECT * FROM operations WHERE op_id = ?",
                    (op_id,),
                ).fetchone()
                if row is None:
                    raise OperationNotFoundError(f"operation {op_id} was not found")
                record = self._decode_record(row)
                if (
                    record.revision != expected_revision
                    or record.status is not expected
                ):
                    return False
                updated_at_ns = _next_timestamp_ns(record.updated_at_ns)
                cursor = connection.execute(
                    """
                    UPDATE operations
                    SET status = ?, revision = revision + 1, updated_at_ns = ?
                    WHERE op_id = ? AND revision = ? AND status = ?
                    """,
                    (
                        target.value,
                        updated_at_ns,
                        op_id,
                        expected_revision,
                        expected.value,
                    ),
                )
                return cursor.rowcount == 1

            return self._run_write(update)

    def list_recoverable(
        self,
        *,
        op_type: str | None = None,
        limit: int = DEFAULT_RECOVERY_LIMIT,
    ) -> list[OperationRecord]:
        """List unfinished plans without letting one corrupt row block peers.

        A corrupt recoverable row is quarantined by exact row identity and
        revision inside the same write transaction, then the scan continues.
        This makes restart progress deterministic without silently repairing or
        overwriting the immutable plan.
        """

        if op_type is not None:
            op_type = _validate_identifier(op_type, "op_type")
        limit = _validate_positive_int(limit, "limit")
        with self._lock:
            def scan(connection: sqlite3.Connection) -> list[OperationRecord]:
                recovered: list[OperationRecord] = []
                cursor: tuple[object, object] | None = None
                while len(recovered) < limit:
                    batch_size = min(
                        RECOVERY_SCAN_BATCH,
                        limit - len(recovered),
                    )
                    if cursor is None:
                        if op_type is None:
                            rows = connection.execute(
                                """
                                SELECT rowid AS _ledger_rowid, * FROM operations
                                WHERE status NOT IN ('committed', 'quarantined')
                                ORDER BY created_at_ns ASC, op_id ASC
                                LIMIT ?
                                """,
                                (batch_size,),
                            ).fetchall()
                        else:
                            rows = connection.execute(
                                """
                                SELECT rowid AS _ledger_rowid, * FROM operations
                                WHERE op_type = ?
                                  AND status NOT IN ('committed', 'quarantined')
                                ORDER BY created_at_ns ASC, op_id ASC
                                LIMIT ?
                                """,
                                (op_type, batch_size),
                            ).fetchall()
                    else:
                        if op_type is None:
                            rows = connection.execute(
                                """
                                SELECT rowid AS _ledger_rowid, * FROM operations
                                WHERE status NOT IN ('committed', 'quarantined')
                                  AND (
                                      created_at_ns > ? OR
                                      (created_at_ns = ? AND op_id > ?)
                                  )
                                ORDER BY created_at_ns ASC, op_id ASC
                                LIMIT ?
                                """,
                                (cursor[0], cursor[0], cursor[1], batch_size),
                            ).fetchall()
                        else:
                            rows = connection.execute(
                                """
                                SELECT rowid AS _ledger_rowid, * FROM operations
                                WHERE op_type = ?
                                  AND status NOT IN ('committed', 'quarantined')
                                  AND (
                                      created_at_ns > ? OR
                                      (created_at_ns = ? AND op_id > ?)
                                  )
                                ORDER BY created_at_ns ASC, op_id ASC
                                LIMIT ?
                                """,
                                (
                                    op_type,
                                    cursor[0],
                                    cursor[0],
                                    cursor[1],
                                    batch_size,
                                ),
                            ).fetchall()
                    if not rows:
                        break
                    for row in rows:
                        cursor = (row["created_at_ns"], row["op_id"])
                        try:
                            recovered.append(self._decode_record(row))
                        except OperationCorruptionError:
                            self._quarantine_corrupt_row(connection, row)
                return recovered

            return self._run_write(scan)

    @staticmethod
    def _quarantine_corrupt_row(
        connection: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> bool:
        """Best-effort exact isolation used only after decode proves corruption."""

        rowid = row["_ledger_rowid"]
        revision = row["revision"]
        status = row["status"]
        updated_at_ns = row["updated_at_ns"]
        if (
            type(rowid) is not int
            or rowid <= 0
            or type(revision) is not int
            or revision < 0
            or revision >= SQLITE_MAX_INTEGER
            or type(status) is not str
            or type(updated_at_ns) is not int
            or updated_at_ns < 0
            or updated_at_ns >= SQLITE_MAX_INTEGER
        ):
            # Metadata this damaged cannot be repaired safely.  It is skipped
            # for this scan, so healthy operations still recover; an operator
            # can inspect/quarantine it offline.
            return False
        try:
            cursor = connection.execute(
                """
                UPDATE operations
                SET status = 'quarantined', quarantine_reason = 'corruption',
                    revision = revision + 1, updated_at_ns = ?
                WHERE rowid = ? AND revision = ? AND status = ?
                """,
                (
                    _next_timestamp_ns(updated_at_ns),
                    rowid,
                    revision,
                    status,
                ),
            )
        except sqlite3.IntegrityError:
            # A separately corrupted constrained field can make even the
            # isolation update invalid.  Do not turn it into a recovery-wide
            # denial of service.
            return False
        return cursor.rowcount == 1

    def quarantine(
        self,
        op_id: str,
        *,
        reason: QuarantineReason | str,
        expected_revision: int | None = None,
        expected_status: OperationStatus | str | None = None,
    ) -> bool:
        """Atomically quarantine exactly one corrupt or precondition-bad row."""

        op_id = _validate_identifier(op_id, "op_id")
        quarantine_reason = _coerce_quarantine_reason(reason)
        if expected_revision is not None:
            expected_revision = _validate_nonnegative_int(
                expected_revision,
                "expected_revision",
            )
        expected = (
            None
            if expected_status is None
            else _coerce_status(expected_status, "expected_status")
        )

        with self._lock:
            def update(connection: sqlite3.Connection) -> bool:
                row = connection.execute(
                    """
                    SELECT revision, status, updated_at_ns
                    FROM operations WHERE op_id = ?
                    """,
                    (op_id,),
                ).fetchone()
                if row is None:
                    raise OperationNotFoundError(f"operation {op_id} was not found")
                revision = row["revision"]
                status = row["status"]
                updated_at_ns = row["updated_at_ns"]
                if type(revision) is not int or revision < 0:
                    raise OperationCorruptionError(
                        f"operation {op_id} has invalid revision"
                    )
                if type(updated_at_ns) is not int or updated_at_ns < 0:
                    raise OperationCorruptionError(
                        f"operation {op_id} has invalid timestamp"
                    )
                if expected_revision is not None and revision != expected_revision:
                    return False
                if expected is not None and status != expected.value:
                    return False
                if status == OperationStatus.QUARANTINED.value:
                    return False
                new_timestamp = _next_timestamp_ns(updated_at_ns)
                cursor = connection.execute(
                    """
                    UPDATE operations
                    SET status = ?, quarantine_reason = ?,
                        revision = revision + 1, updated_at_ns = ?
                    WHERE op_id = ? AND revision = ? AND status = ?
                    """,
                    (
                        OperationStatus.QUARANTINED.value,
                        quarantine_reason.value,
                        new_timestamp,
                        op_id,
                        revision,
                        status,
                    ),
                )
                return cursor.rowcount == 1

            return self._run_write(update)

    def purge_terminal(
        self,
        retention_seconds: int | float,
        *,
        now_ns: int | None = None,
        limit: int = DEFAULT_RECOVERY_LIMIT,
    ) -> int:
        """Delete old terminal rows only; active work is never selected."""

        if type(retention_seconds) is int:
            valid_retention = retention_seconds >= 0
        elif type(retention_seconds) is float:
            valid_retention = (
                math.isfinite(retention_seconds) and retention_seconds >= 0
            )
        else:
            valid_retention = False
        if not valid_retention:
            raise OperationValidationError(
                "retention_seconds must be a finite non-negative number"
            )
        limit = _validate_positive_int(limit, "limit")
        if now_ns is None:
            effective_now_ns = time.time_ns()
        else:
            effective_now_ns = _validate_nonnegative_int(now_ns, "now_ns")
        # Avoid converting a huge Python integer/float through a SQLite-bound
        # intermediate.  Any retention at least as old as the epoch-to-now
        # interval simply has a zero cutoff.
        if retention_seconds >= (effective_now_ns / 1_000_000_000):
            cutoff_ns = 0
        else:
            retention_ns = int(retention_seconds * 1_000_000_000)
            cutoff_ns = effective_now_ns - retention_ns

        with self._lock:
            def purge(connection: sqlite3.Connection) -> int:
                cursor = connection.execute(
                    """
                    DELETE FROM operations
                    WHERE rowid IN (
                        SELECT rowid FROM operations
                        WHERE status IN ('committed', 'quarantined')
                          AND updated_at_ns <= ?
                        ORDER BY updated_at_ns ASC, op_id ASC
                        LIMIT ?
                    )
                    """,
                    (cutoff_ns, limit),
                )
                return cursor.rowcount

            return self._run_write(purge)

    def checkpoint(self, mode: str = "PASSIVE") -> CheckpointResult:
        """Run an allowlisted WAL checkpoint and return SQLite counters."""

        if type(mode) is not str or mode.upper() not in {
            "PASSIVE",
            "FULL",
            "RESTART",
            "TRUNCATE",
        }:
            raise OperationValidationError("invalid WAL checkpoint mode")
        normalized = mode.upper()
        with self._lock:
            connection = self._require_connection()
            try:
                row = connection.execute(
                    f"PRAGMA wal_checkpoint({normalized})"
                ).fetchone()
            except sqlite3.DatabaseError as exc:
                raise OperationLedgerIOError("WAL checkpoint failed") from exc
            if row is None or len(row) != 3:
                raise OperationLedgerIOError("WAL checkpoint returned invalid data")
            return CheckpointResult(
                busy=int(row[0]),
                log_frames=int(row[1]),
                checkpointed_frames=int(row[2]),
            )

    def close(self) -> None:
        """Checkpoint and close once; repeated closes are harmless."""

        with self._lock:
            connection = self._connection
            if connection is None:
                return
            checkpoint_error: BaseException | None = None
            try:
                self.checkpoint("PASSIVE")
            except BaseException as exc:
                checkpoint_error = exc
            finally:
                self._connection = None
                try:
                    connection.close()
                except sqlite3.DatabaseError as exc:
                    if checkpoint_error is None:
                        checkpoint_error = OperationLedgerIOError(
                            "could not close operation ledger"
                        )
                        checkpoint_error.__cause__ = exc
            if checkpoint_error is not None:
                raise checkpoint_error

    def __enter__(self) -> "OperationLedger":
        self._require_connection()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()


__all__ = [
    "CheckpointResult",
    "DEFAULT_RECOVERY_LIMIT",
    "MAX_IDENTIFIER_LENGTH",
    "MAX_PLAN_BYTES",
    "MAX_PLAN_DEPTH",
    "MAX_PLAN_ITEMS",
    "OperationConflictError",
    "OperationCorruptionError",
    "OperationLedger",
    "OperationLedgerClosedError",
    "OperationLedgerError",
    "OperationLedgerIOError",
    "OperationNotFoundError",
    "OperationPreconditionError",
    "OperationRecord",
    "OperationStatus",
    "OperationValidationError",
    "QuarantineReason",
    "SCHEMA_VERSION",
    "canonical_plan_json",
]
