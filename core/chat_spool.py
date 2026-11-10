"""Small durable filesystem queues for dashboard/brain chat hand-off.

The protocol deliberately provides *at-least-once transport*, not exactly-once
execution.  Request claims are therefore never replayed after their lease: a
stale request is acknowledged when its response is already durable, otherwise
it is quarantined in the dead-letter directory.  Stale responses are safe to
requeue because clients deduplicate them by request/message id.

All JSON envelopes are immutable.  Publishing writes and fsyncs a hidden file
in the destination directory before an atomic same-filesystem ``os.replace``;
state transitions only rename or remove the finished envelope.
"""

from __future__ import annotations

import json
import math
import os
import re
import secrets
import time
from contextlib import contextmanager
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from typing import Callable, Iterable, Iterator, Optional


SCHEMA_VERSION = 1
REQUEST_KIND = "chat.request"
RESPONSE_KIND = "chat.response"

_MESSAGE_ID_RE = re.compile(r"^[0-9]{20}-[0-9a-f]{32}$", re.ASCII)
_RECEIPT_RE = re.compile(
    r"^(?P<id>[0-9]{20}-[0-9a-f]{32})\."
    r"(?P<claimed>[0-9]{20})\.(?P<token>[0-9a-f]{32})$",
    re.ASCII,
)
_REASON_RE = re.compile(r"^[a-z0-9_-]{1,32}$", re.ASCII)


class ChatSpoolError(RuntimeError):
    """Base class for durable chat spool errors."""


class ChatSpoolIOError(ChatSpoolError):
    """A filesystem operation failed while preserving spool state."""


class InvalidEnvelope(ChatSpoolError, ValueError):
    """An envelope does not satisfy the on-disk schema."""


class InvalidReceipt(ChatSpoolError, ValueError):
    """A claim receipt is malformed or would not remain path-contained."""


class PayloadTooLarge(ChatSpoolError, ValueError):
    """Message content exceeds the configured UTF-8 byte limit."""


class QueueFull(ChatSpoolError):
    """The bounded active queue has no free slot."""


class SpoolLockTimeout(ChatSpoolError, TimeoutError):
    """The cross-process enqueue lock could not be acquired in time."""


def _translate_os_errors(operation: str):
    """Keep filesystem failures inside the public typed spool contract."""

    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            try:
                return function(*args, **kwargs)
            except ChatSpoolError:
                raise
            except OSError as exc:
                raise ChatSpoolIOError(f"Chat spool {operation} failed") from exc

        return wrapped

    return decorate


@dataclass(frozen=True)
class ChatEnvelope:
    schema: int
    id: str
    kind: str
    created_at_ns: int
    role: str
    content: str
    reply_to: Optional[str]

    def as_dict(self) -> dict:
        return {
            "schema": self.schema,
            "id": self.id,
            "kind": self.kind,
            "created_at_ns": self.created_at_ns,
            "role": self.role,
            "content": self.content,
            "reply_to": self.reply_to,
        }


@dataclass(frozen=True)
class Claim:
    envelope: ChatEnvelope
    receipt: str


@dataclass(frozen=True)
class PublishResult:
    message_id: str
    created: bool


@dataclass(frozen=True)
class RecoveryReport:
    acknowledged_requests: int = 0
    dead_requests: int = 0
    requeued_responses: int = 0


class ChatSpool:
    """One side of a durable request/response filesystem spool.

    ``queue_type`` must be ``"request"`` or ``"response"``.  Separate
    instances should share the same ``root`` for correlation-based recovery.
    The active count includes pending and processing files; dead letters are
    separately capped by ``max_dead_count``.
    """

    _STATE_NAMES = ("pending", "processing", "staged", "dead", "completed")

    @_translate_os_errors("initialization")
    def __init__(
        self,
        root: os.PathLike | str,
        queue_type: str,
        *,
        max_payload_bytes: int = 64 * 1024,
        max_count: int = 1_000,
        max_dead_count: Optional[int] = None,
        lease_seconds: float = 300.0,
        retention_seconds: Optional[float] = None,
        lock_timeout_seconds: float = 10.0,
        clock_ns: Callable[[], int] = time.time_ns,
    ):
        if queue_type not in {"request", "response"}:
            raise ValueError("queue_type must be 'request' or 'response'")
        if max_payload_bytes <= 0:
            raise ValueError("max_payload_bytes must be positive")
        if max_count <= 0:
            raise ValueError("max_count must be positive")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        if retention_seconds is not None and (
            not math.isfinite(float(retention_seconds))
            or float(retention_seconds) <= 0.0
        ):
            raise ValueError("retention_seconds must be finite and positive")

        self.queue_type = queue_type
        self.kind = REQUEST_KIND if queue_type == "request" else RESPONSE_KIND
        self.max_payload_bytes = int(max_payload_bytes)
        self.max_count = int(max_count)
        self.max_dead_count = int(max_dead_count or max_count)
        self.lease_ns = int(float(lease_seconds) * 1_000_000_000)
        self.retention_ns = (
            None
            if retention_seconds is None
            else int(float(retention_seconds) * 1_000_000_000)
        )
        self.lock_timeout_seconds = float(lock_timeout_seconds)
        self._clock_ns = clock_ns

        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        queue_name = "requests" if queue_type == "request" else "responses"
        self.queue_dir = self._contained(self.root, queue_name)
        self.queue_dir.mkdir(parents=True, exist_ok=True)

        for state in self._STATE_NAMES:
            state_dir = self._contained(self.queue_dir, state)
            if state_dir.is_symlink():
                raise ChatSpoolError(f"Spool state directory may not be a symlink: {state}")
            state_dir.mkdir(parents=True, exist_ok=True)

        self.pending_dir = self._contained(self.queue_dir, "pending")
        self.processing_dir = self._contained(self.queue_dir, "processing")
        # Responses may be durably staged after execution if the browser-facing
        # queue fills in the small race between preflight and publication.
        self.staged_dir = self._contained(self.queue_dir, "staged")
        self.dead_dir = self._contained(self.queue_dir, "dead")
        # Completed response envelopes are bounded delivery tombstones. They
        # preserve publish idempotency and let stale request recovery recognize
        # a response even after the browser has acknowledged it.
        self.completed_dir = self._contained(self.queue_dir, "completed")
        self._lock_file = self._contained(self.queue_dir, ".enqueue.lock")
        self._ensure_lock_file()

    @staticmethod
    def _contained(parent: Path, name: str) -> Path:
        if not name or name in {".", ".."} or "/" in name or "\\" in name:
            raise ChatSpoolError("Unsafe spool path component")
        resolved_parent = parent.resolve()
        candidate = (resolved_parent / name).resolve(strict=False)
        if candidate.parent != resolved_parent:
            raise ChatSpoolError("Spool path escaped its configured parent")
        return candidate

    def _state_path(self, directory: Path, filename: str) -> Path:
        resolved_root = self.root.resolve()
        resolved_queue = self.queue_dir.resolve()
        resolved_directory = directory.resolve()
        if self.queue_dir.is_symlink() or resolved_queue.parent != resolved_root:
            raise ChatSpoolError("Spool queue directory escaped its configured root")
        if directory.is_symlink() or resolved_directory.parent != resolved_queue:
            raise ChatSpoolError("Spool state directory escaped its configured queue")
        return self._contained(resolved_directory, filename)

    def _ensure_lock_file(self) -> None:
        fd = os.open(str(self._lock_file), os.O_CREAT | os.O_RDWR, 0o600)
        try:
            # Windows byte-range locking requires the byte to exist. Concurrent
            # creators can safely write the same single zero byte at offset zero.
            if os.fstat(fd).st_size == 0:
                os.write(fd, b"\0")
                os.fsync(fd)
        finally:
            os.close(fd)

    @contextmanager
    def _enqueue_lock(self) -> Iterator[None]:
        deadline = time.monotonic() + self.lock_timeout_seconds
        lock_stream = open(self._lock_file, "r+b", buffering=0)
        acquired = False

        if os.name == "nt":
            import msvcrt

            while not acquired:
                try:
                    lock_stream.seek(0)
                    msvcrt.locking(lock_stream.fileno(), msvcrt.LK_NBLCK, 1)
                    acquired = True
                except OSError:
                    if time.monotonic() >= deadline:
                        lock_stream.close()
                        raise SpoolLockTimeout(
                            "Timed out acquiring chat spool enqueue lock"
                        )
                    time.sleep(0.005)
        else:
            import fcntl

            while not acquired:
                try:
                    fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                except (BlockingIOError, OSError):
                    if time.monotonic() >= deadline:
                        lock_stream.close()
                        raise SpoolLockTimeout(
                            "Timed out acquiring chat spool enqueue lock"
                        )
                    time.sleep(0.005)

        try:
            yield
        finally:
            try:
                if os.name == "nt":
                    lock_stream.seek(0)
                    msvcrt.locking(lock_stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(lock_stream.fileno(), fcntl.LOCK_UN)
            finally:
                lock_stream.close()

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

    def _commit_temp(self, temp_path: Path, final_path: Path) -> None:
        os.replace(temp_path, final_path)
        self._fsync_directory(final_path.parent)

    def _atomic_write_envelope(self, envelope: ChatEnvelope, final_path: Path) -> None:
        serialized = json.dumps(
            envelope.as_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        # Content has its own exact bound. This secondary bound rejects corrupt
        # or unexpectedly expanded schemas without relying on parser behavior.
        if len(serialized) > self.max_payload_bytes + 1_024:
            raise PayloadTooLarge("Serialized chat envelope is too large")

        temp_path = self._state_path(
            final_path.parent, f".tmp-{envelope.id}-{secrets.token_hex(16)}"
        )
        fd: Optional[int] = None
        try:
            fd = os.open(str(temp_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "wb") as stream:
                fd = None
                stream.write(serialized)
                stream.flush()
                os.fsync(stream.fileno())
            self._commit_temp(temp_path, final_path)
        finally:
            if fd is not None:
                os.close(fd)
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass

    def _make_id(self) -> str:
        timestamp_ns = int(self._clock_ns())
        if timestamp_ns < 0 or timestamp_ns >= 10**20:
            raise ChatSpoolError("Clock returned an unsupported timestamp")
        return f"{timestamp_ns:020d}-{secrets.token_hex(16)}"

    def _validate_content(self, content: object) -> str:
        if not isinstance(content, str):
            raise InvalidEnvelope("Chat content must be a string")
        if not content.strip():
            raise InvalidEnvelope("Chat content may not be empty")
        if len(content.encode("utf-8")) > self.max_payload_bytes:
            raise PayloadTooLarge("Chat content exceeds the configured byte limit")
        return content

    def _validate_envelope(self, envelope: ChatEnvelope) -> ChatEnvelope:
        if type(envelope.schema) is not int or envelope.schema != SCHEMA_VERSION:
            raise InvalidEnvelope("Unsupported chat envelope schema")
        if not isinstance(envelope.id, str) or not _MESSAGE_ID_RE.fullmatch(envelope.id):
            raise InvalidEnvelope("Invalid chat message id")
        if envelope.kind != self.kind:
            raise InvalidEnvelope("Envelope kind does not match this spool")
        if type(envelope.created_at_ns) is not int or envelope.created_at_ns < 0:
            raise InvalidEnvelope("Invalid envelope creation timestamp")
        self._validate_content(envelope.content)

        if self.queue_type == "request":
            if envelope.role != "user" or envelope.reply_to is not None:
                raise InvalidEnvelope("Invalid request envelope routing fields")
        else:
            if envelope.role != "aura":
                raise InvalidEnvelope("Invalid response role")
            if envelope.reply_to != envelope.id or not _MESSAGE_ID_RE.fullmatch(
                envelope.reply_to or ""
            ):
                raise InvalidEnvelope("Response must be keyed by its request id")
        return envelope

    def _deserialize(self, raw: bytes) -> ChatEnvelope:
        if len(raw) > self.max_payload_bytes + 1_024:
            raise PayloadTooLarge("Serialized chat envelope is too large")
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InvalidEnvelope("Invalid envelope JSON") from exc
        expected = {
            "schema", "id", "kind", "created_at_ns", "role", "content", "reply_to"
        }
        if not isinstance(data, dict) or set(data) != expected:
            raise InvalidEnvelope("Envelope fields do not match the schema")
        return self._validate_envelope(ChatEnvelope(**data))

    def _active_count_unsafe(self) -> int:
        return sum(1 for _ in self.pending_dir.glob("*.json")) + sum(
            1 for _ in self.processing_dir.glob("*.json")
        )

    def _find_message_path(self, message_id: str) -> Optional[Path]:
        if not _MESSAGE_ID_RE.fullmatch(message_id):
            raise InvalidEnvelope("Invalid chat message id")
        pending = self._state_path(self.pending_dir, f"{message_id}.json")
        if pending.is_file():
            return pending
        completed = self._state_path(self.completed_dir, f"{message_id}.json")
        if completed.is_file():
            return completed
        staged = self._state_path(self.staged_dir, f"{message_id}.json")
        if staged.is_file():
            return staged
        for directory in (self.processing_dir, self.dead_dir):
            for candidate in directory.glob(f"{message_id}.*.json"):
                if candidate.is_file():
                    return candidate
        return None

    @_translate_os_errors("lookup")
    def contains(self, message_id: str) -> bool:
        with self._enqueue_lock():
            return self._find_message_path(message_id) is not None

    @_translate_os_errors("status lookup")
    def message_state(self, message_id: str) -> Optional[str]:
        """Return the durable state for one validated message id."""
        with self._enqueue_lock():
            path = self._find_message_path(message_id)
            return None if path is None else path.parent.name

    @_translate_os_errors("retention lookup")
    def retention_expired(self, message_id: str) -> bool:
        """Report whether an absent id is older than this spool's retention."""
        if not isinstance(message_id, str) or not _MESSAGE_ID_RE.fullmatch(message_id):
            raise InvalidEnvelope("Invalid chat message id")
        if self.retention_ns is None:
            return False
        created_ns = int(message_id[:20])
        return int(self._clock_ns()) - created_ns >= self.retention_ns

    @_translate_os_errors("request publication")
    def enqueue_request(self, content: str) -> PublishResult:
        if self.queue_type != "request":
            raise ChatSpoolError("enqueue_request requires a request spool")
        content = self._validate_content(content)

        with self._enqueue_lock():
            if self._active_count_unsafe() >= self.max_count:
                raise QueueFull("Chat request queue is full")
            while True:
                message_id = self._make_id()
                final_path = self._state_path(self.pending_dir, f"{message_id}.json")
                if self._find_message_path(message_id) is None:
                    break
            envelope = self._validate_envelope(
                ChatEnvelope(
                    schema=SCHEMA_VERSION,
                    id=message_id,
                    kind=REQUEST_KIND,
                    created_at_ns=int(self._clock_ns()),
                    role="user",
                    content=content,
                    reply_to=None,
                )
            )
            self._atomic_write_envelope(envelope, final_path)
            return PublishResult(message_id=message_id, created=True)

    @_translate_os_errors("capacity check")
    def has_capacity(self) -> bool:
        """Return a lock-consistent snapshot of visible queue capacity."""
        with self._enqueue_lock():
            return self._active_count_unsafe() < self.max_count

    @_translate_os_errors("response publication")
    def publish_response(
        self,
        request_id: str,
        content: str,
        *,
        stage_if_full: bool = False,
    ) -> PublishResult:
        if self.queue_type != "response":
            raise ChatSpoolError("publish_response requires a response spool")
        if not isinstance(request_id, str) or not _MESSAGE_ID_RE.fullmatch(request_id):
            raise InvalidEnvelope("Invalid request id for response")
        content = self._validate_content(content)

        with self._enqueue_lock():
            if self._find_message_path(request_id) is not None:
                return PublishResult(message_id=request_id, created=False)
            destination = self.pending_dir
            if self._active_count_unsafe() >= self.max_count:
                if not stage_if_full:
                    raise QueueFull("Chat response queue is full")
                staged_count = sum(1 for _ in self.staged_dir.glob("*.json"))
                if staged_count >= self.max_count:
                    raise QueueFull("Chat response staging queue is full")
                destination = self.staged_dir
            envelope = self._validate_envelope(
                ChatEnvelope(
                    schema=SCHEMA_VERSION,
                    id=request_id,
                    kind=RESPONSE_KIND,
                    created_at_ns=int(self._clock_ns()),
                    role="aura",
                    content=content,
                    reply_to=request_id,
                )
            )
            final_path = self._state_path(destination, f"{request_id}.json")
            self._atomic_write_envelope(envelope, final_path)
            return PublishResult(message_id=request_id, created=True)

    @_translate_os_errors("proactive publication")
    def publish_proactive(self, content: str) -> PublishResult:
        """Publish a message Aura starts herself (no request to answer).

        Uses the response envelope unchanged: it is keyed by a fresh id of its
        own, so delivery, ACK and expiry work exactly as for replies. Keep
        proactive messages in their own spool (see
        ``create_configured_proactive_spool``) so browsers can claim them
        without knowing the id in advance.
        """
        if self.queue_type != "response":
            raise ChatSpoolError("publish_proactive requires a response spool")
        content = self._validate_content(content)

        with self._enqueue_lock():
            if self._active_count_unsafe() >= self.max_count:
                raise QueueFull("Proactive message queue is full")
            while True:
                message_id = self._make_id()
                if self._find_message_path(message_id) is None:
                    break
            envelope = self._validate_envelope(
                ChatEnvelope(
                    schema=SCHEMA_VERSION,
                    id=message_id,
                    kind=RESPONSE_KIND,
                    created_at_ns=int(self._clock_ns()),
                    role="aura",
                    content=content,
                    reply_to=message_id,
                )
            )
            final_path = self._state_path(self.pending_dir, f"{message_id}.json")
            self._atomic_write_envelope(envelope, final_path)
            return PublishResult(message_id=message_id, created=True)

    @_translate_os_errors("staged response promotion")
    def promote_staged(self, limit: int = 100) -> int:
        """Move durable response outbox entries into browser delivery capacity."""
        if self.queue_type != "response":
            raise ChatSpoolError("promote_staged requires a response spool")
        if type(limit) is not int or limit <= 0 or limit > 100:
            raise ValueError("promotion limit must be between 1 and 100")

        promoted = 0
        with self._enqueue_lock():
            capacity = max(0, self.max_count - self._active_count_unsafe())
            for staged_path in sorted(self.staged_dir.glob("*.json"), key=lambda p: p.name):
                if promoted >= min(limit, capacity):
                    break
                message_id = staged_path.stem
                if not _MESSAGE_ID_RE.fullmatch(message_id):
                    continue
                pending_path = self._state_path(
                    self.pending_dir, f"{message_id}.json"
                )
                try:
                    os.replace(staged_path, pending_path)
                except FileNotFoundError:
                    continue
                promoted += 1
            if promoted:
                self._fsync_directory(self.pending_dir)
                self._fsync_directory(self.staged_dir)
        return promoted

    @_translate_os_errors("response expiration")
    def expire_stale_deliveries(self) -> int:
        """Quarantine abandoned visible responses and release capacity.

        Processing responses are governed by the normal claim lease. Callers
        recover those first; this method then expires pending/staged envelopes
        that have exceeded their configured delivery-retention window.
        """
        if self.queue_type != "response":
            raise ChatSpoolError("delivery expiration requires a response spool")
        if self.retention_ns is None:
            return 0

        now_ns = int(self._clock_ns())
        if now_ns < 0 or now_ns >= 10**20:
            raise ChatSpoolError("Clock returned an unsupported timestamp")
        expired = 0
        with self._enqueue_lock():
            for directory in (self.pending_dir, self.staged_dir):
                for source in sorted(directory.glob("*.json"), key=lambda p: p.name):
                    message_id = source.stem
                    if not _MESSAGE_ID_RE.fullmatch(message_id):
                        continue
                    reason = "delivery_expired"
                    try:
                        envelope = self._deserialize(source.read_bytes())
                        if envelope.id != message_id:
                            raise InvalidEnvelope(
                                "Envelope id does not match its filename"
                            )
                    except (ChatSpoolError, ValueError):
                        reason = "invalid_envelope"
                        envelope = None
                    if (
                        envelope is not None
                        and now_ns - envelope.created_at_ns < self.retention_ns
                    ):
                        continue

                    receipt = (
                        f"{message_id}.{now_ns:020d}.{secrets.token_hex(16)}"
                    )
                    destination = self._dead_letter_path(receipt, reason)
                    try:
                        os.replace(source, destination)
                    except FileNotFoundError:
                        continue
                    expired += 1

            if expired:
                self._fsync_directory(self.dead_dir)
                self._fsync_directory(self.pending_dir)
                self._fsync_directory(self.staged_dir)
                self._prune_directory(self.dead_dir, self.max_dead_count)
        return expired

    def _processing_path(self, receipt: str) -> Path:
        if not isinstance(receipt, str) or not _RECEIPT_RE.fullmatch(receipt):
            raise InvalidReceipt("Malformed chat claim receipt")
        return self._state_path(self.processing_dir, f"{receipt}.json")

    def _dead_letter_path(self, receipt: str, reason: str) -> Path:
        if not _RECEIPT_RE.fullmatch(receipt):
            raise InvalidReceipt("Malformed chat claim receipt")
        if not isinstance(reason, str) or not _REASON_RE.fullmatch(reason):
            raise InvalidReceipt("Malformed dead-letter reason")
        return self._state_path(self.dead_dir, f"{receipt}.{reason}.json")

    @staticmethod
    def _prune_directory(directory: Path, limit: int) -> None:
        try:
            files = sorted(
                directory.glob("*.json"),
                key=lambda path: (path.stat().st_mtime_ns, path.name),
            )
        except OSError:
            return
        for path in files[: max(0, len(files) - limit)]:
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    def _move_processing_to_dead(self, receipt: str, reason: str) -> bool:
        source = self._processing_path(receipt)
        destination = self._dead_letter_path(receipt, reason)
        with self._enqueue_lock():
            try:
                os.replace(source, destination)
            except FileNotFoundError:
                return False
            self._fsync_directory(self.dead_dir)
            self._prune_directory(self.dead_dir, self.max_dead_count)
            return True

    @_translate_os_errors("peek")
    def peek_next(self) -> Optional[ChatEnvelope]:
        """Oldest pending envelope without claiming it (no lease starts).

        Lets a consumer decide to leave a message waiting (e.g. Aura is
        asleep) without risking lease expiry into the dead-letter queue.
        """
        for pending_path in sorted(self.pending_dir.glob("*.json"), key=lambda p: p.name):
            if not _MESSAGE_ID_RE.fullmatch(pending_path.stem):
                continue
            try:
                envelope = self._deserialize(pending_path.read_bytes())
            except FileNotFoundError:
                continue  # claimed concurrently
            except (ChatSpoolError, ValueError):
                continue  # claim() quarantines invalid envelopes
            if envelope.id == pending_path.stem:
                return envelope
        return None

    @_translate_os_errors("claim")
    def claim(
        self,
        limit: int = 1,
        *,
        message_ids: Optional[Iterable[str]] = None,
    ) -> list[Claim]:
        if type(limit) is not int or limit <= 0 or limit > 100:
            raise ValueError("claim limit must be between 1 and 100")
        allowed_ids = None
        if message_ids is not None:
            requested_ids = list(message_ids)
            if len(requested_ids) > 100:
                raise ValueError("at most 100 message ids may be claimed")
            if any(
                not isinstance(message_id, str)
                or not _MESSAGE_ID_RE.fullmatch(message_id)
                for message_id in requested_ids
            ):
                raise InvalidEnvelope("Invalid message id claim filter")
            allowed_ids = set(requested_ids)

        claims: list[Claim] = []
        for pending_path in sorted(self.pending_dir.glob("*.json"), key=lambda p: p.name):
            if len(claims) >= limit:
                break
            message_id = pending_path.stem
            if not _MESSAGE_ID_RE.fullmatch(message_id):
                # Files not generated by this module are deliberately ignored;
                # they cannot influence a contained claim path.
                continue
            if allowed_ids is not None and message_id not in allowed_ids:
                continue
            claimed_ns = int(self._clock_ns())
            if claimed_ns < 0 or claimed_ns >= 10**20:
                raise ChatSpoolError("Clock returned an unsupported timestamp")
            receipt = f"{message_id}.{claimed_ns:020d}.{secrets.token_hex(16)}"
            processing_path = self._processing_path(receipt)
            with self._enqueue_lock():
                try:
                    os.replace(pending_path, processing_path)
                except FileNotFoundError:
                    continue

            try:
                raw_envelope = processing_path.read_bytes()
            except OSError:
                # A transient read failure is not proof of corruption. Leave
                # the claim in processing so lease recovery can reconcile it.
                raise
            try:
                envelope = self._deserialize(raw_envelope)
                if envelope.id != message_id:
                    raise InvalidEnvelope("Envelope id does not match its filename")
            except (ChatSpoolError, ValueError):
                self._move_processing_to_dead(receipt, "invalid_envelope")
                continue
            if (
                self.queue_type == "response"
                and self.retention_ns is not None
                and claimed_ns - envelope.created_at_ns >= self.retention_ns
            ):
                self._move_processing_to_dead(receipt, "delivery_expired")
                continue
            claims.append(Claim(envelope=envelope, receipt=receipt))
        return claims

    @_translate_os_errors("acknowledgement")
    def ack(self, receipt: str) -> bool:
        processing_path = self._processing_path(receipt)
        if self.queue_type == "request":
            with self._enqueue_lock():
                try:
                    processing_path.unlink()
                except FileNotFoundError:
                    return False
                self._fsync_directory(self.processing_dir)
                return True

        match = _RECEIPT_RE.fullmatch(receipt)
        # _processing_path already validated this receipt.
        message_id = match.group("id")
        completed_path = self._state_path(self.completed_dir, f"{message_id}.json")
        with self._enqueue_lock():
            if completed_path.exists():
                try:
                    processing_path.unlink()
                except FileNotFoundError:
                    return False
            else:
                try:
                    os.replace(processing_path, completed_path)
                except FileNotFoundError:
                    return False
            self._fsync_directory(self.completed_dir)
            self._prune_directory(self.completed_dir, self.max_count)
            return True

    @_translate_os_errors("claim release")
    def release(self, receipt: str) -> bool:
        """Return an unexecuted claim to pending without changing its bytes.

        Consumers may use this only when admission failed before any handler
        began (for example actor backpressure). Once execution starts, retrying
        would risk duplicating side effects and the claim must be ACKed after a
        durable response or moved to the dead-letter queue.
        """
        processing_path = self._processing_path(receipt)
        match = _RECEIPT_RE.fullmatch(receipt)
        message_id = match.group("id")
        pending_path = self._state_path(self.pending_dir, f"{message_id}.json")
        with self._enqueue_lock():
            if pending_path.exists():
                return False
            try:
                os.replace(processing_path, pending_path)
            except FileNotFoundError:
                return False
            self._fsync_directory(self.pending_dir)
            return True

    @_translate_os_errors("dead-letter transition")
    def dead_letter(self, receipt: str, reason: str = "consumer_error") -> bool:
        return self._move_processing_to_dead(receipt, reason)

    @_translate_os_errors("lease recovery")
    def recover_stale(self, response_spool: Optional["ChatSpool"] = None) -> RecoveryReport:
        if self.queue_type == "request":
            if response_spool is None or response_spool.queue_type != "response":
                raise ValueError("Request recovery requires the paired response spool")

        acknowledged = 0
        dead = 0
        requeued = 0
        now_ns = int(self._clock_ns())

        for processing_path in sorted(self.processing_dir.glob("*.json"), key=lambda p: p.name):
            receipt = processing_path.stem
            match = _RECEIPT_RE.fullmatch(receipt)
            if not match:
                continue
            claimed_ns = int(match.group("claimed"))
            if now_ns - claimed_ns < self.lease_ns:
                continue
            message_id = match.group("id")

            if self.queue_type == "request":
                # Never blindly replay a possibly side-effecting interaction.
                if response_spool.contains(message_id):
                    if self.ack(receipt):
                        acknowledged += 1
                elif self._move_processing_to_dead(receipt, "stale_no_response"):
                    dead += 1
                continue

            pending_path = self._state_path(self.pending_dir, f"{message_id}.json")
            # Moving processing -> pending can otherwise race the capacity scan
            # between its two directories and momentarily under-count an item.
            with self._enqueue_lock():
                if pending_path.exists():
                    # Defensive duplicate collapse: keep the visible copy.
                    try:
                        processing_path.unlink()
                    except FileNotFoundError:
                        continue
                    requeued += 1
                    continue
                try:
                    os.replace(processing_path, pending_path)
                except FileNotFoundError:
                    continue
                self._fsync_directory(self.pending_dir)
                requeued += 1

        return RecoveryReport(
            acknowledged_requests=acknowledged,
            dead_requests=dead,
            requeued_responses=requeued,
        )

    @_translate_os_errors("statistics scan")
    def stats(self) -> dict[str, int]:
        with self._enqueue_lock():
            return {
                # Staged responses are durable pending delivery, even though they
                # do not consume the visible delivery window yet.
                "pending": sum(1 for _ in self.pending_dir.glob("*.json"))
                + sum(1 for _ in self.staged_dir.glob("*.json")),
                "processing": sum(1 for _ in self.processing_dir.glob("*.json")),
                "dead": sum(1 for _ in self.dead_dir.glob("*.json")),
            }


@_translate_os_errors("configured initialization")
def create_configured_chat_spools() -> tuple[ChatSpool, ChatSpool]:
    """Build the paired queues from the shared project configuration."""
    from config import Config

    common = {
        "max_count": Config.CHAT_SPOOL_MAX_MESSAGES,
        "lease_seconds": Config.CHAT_SPOOL_LEASE_SECONDS,
    }
    requests = ChatSpool(
        Config.CHAT_SPOOL_DIR,
        "request",
        max_payload_bytes=Config.CHAT_REQUEST_MAX_BYTES,
        **common,
    )
    responses = ChatSpool(
        Config.CHAT_SPOOL_DIR,
        "response",
        max_payload_bytes=Config.CHAT_RESPONSE_MAX_BYTES,
        retention_seconds=Config.CHAT_RESPONSE_RETENTION_SECONDS,
        **common,
    )
    return requests, responses


@_translate_os_errors("configured initialization")
def create_configured_proactive_spool() -> ChatSpool:
    """Outbox for messages Aura sends on her own (pings, voiced rumination)."""
    from config import Config

    return ChatSpool(
        Config.CHAT_PROACTIVE_SPOOL_DIR,
        "response",
        max_payload_bytes=Config.CHAT_RESPONSE_MAX_BYTES,
        max_count=Config.CHAT_SPOOL_MAX_MESSAGES,
        lease_seconds=Config.CHAT_SPOOL_LEASE_SECONDS,
        retention_seconds=Config.CHAT_RESPONSE_RETENTION_SECONDS,
    )


__all__ = [
    "ChatEnvelope",
    "ChatSpool",
    "ChatSpoolError",
    "ChatSpoolIOError",
    "Claim",
    "InvalidEnvelope",
    "InvalidReceipt",
    "PayloadTooLarge",
    "PublishResult",
    "QueueFull",
    "RecoveryReport",
    "SpoolLockTimeout",
    "create_configured_chat_spools",
    "create_configured_proactive_spool",
]
