"""Cross-process single-writer lease for durable Aura state.

The lease is intentionally non-expiring.  A live process keeps the file
descriptor open until its owner performs a clean shutdown; the operating
system releases it if the process exits.  The lock file itself is persistent
and must not be deleted because replacing it would create a second lock inode.
"""

from __future__ import annotations

import os
import threading
from enum import Enum
from pathlib import Path
from typing import BinaryIO


class WriterLeaseError(RuntimeError):
    """Base error for the durable-state writer lease."""


class WriterLeaseUnavailable(WriterLeaseError):
    """Raised immediately when another writer already owns the lease."""


class WriterLeaseState(str, Enum):
    NEW = "new"
    HELD = "held"
    RELEASED = "released"


_REGISTRY_LOCK = threading.Lock()
# Keep a strong reference to each owner.  This makes an accidentally orphaned
# lease fail closed for the rest of the process instead of relying on garbage
# collection to decide when another process may write.
_HELD_LEASES: dict[str, object] = {}


def _canonical_path(path: os.PathLike[str] | str) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(os.fspath(path))))


def _try_lock(handle: BinaryIO) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(handle: BinaryIO) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class ProcessWriterLease:
    """A one-shot, process-held exclusive lease on a stable lock file."""

    def __init__(self, path: os.PathLike[str] | str):
        self.path = Path(_canonical_path(path))
        self.state = WriterLeaseState.NEW
        self._handle: BinaryIO | None = None

    def acquire(self) -> "ProcessWriterLease":
        if self.state is not WriterLeaseState.NEW:
            raise WriterLeaseError(
                f"writer lease cannot be acquired from state={self.state.value}"
            )

        canonical = os.fspath(self.path)
        with _REGISTRY_LOCK:
            if canonical in _HELD_LEASES:
                raise WriterLeaseUnavailable(
                    f"durable-state writer lease is already held: {canonical}"
                )

            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                handle = self.path.open("a+b", buffering=0)
            except OSError as exc:
                raise WriterLeaseError(
                    f"could not open durable-state writer lease: {canonical}"
                ) from exc

            try:
                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"\0")
                _try_lock(handle)
            except OSError as exc:
                handle.close()
                raise WriterLeaseUnavailable(
                    f"durable-state writer lease is already held: {canonical}"
                ) from exc

            _HELD_LEASES[canonical] = self
            self._handle = handle
            self.state = WriterLeaseState.HELD
        return self

    def close(self) -> None:
        """Release a held lease once; repeated closes are harmless."""

        if self.state is WriterLeaseState.RELEASED:
            return
        if self.state is WriterLeaseState.NEW:
            self.state = WriterLeaseState.RELEASED
            return

        canonical = os.fspath(self.path)
        with _REGISTRY_LOCK:
            handle = self._handle
            self._handle = None
            try:
                if handle is not None:
                    try:
                        _unlock(handle)
                    finally:
                        handle.close()
            finally:
                if _HELD_LEASES.get(canonical) is self:
                    _HELD_LEASES.pop(canonical, None)
                self.state = WriterLeaseState.RELEASED

    def __enter__(self) -> "ProcessWriterLease":
        return self.acquire()

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
