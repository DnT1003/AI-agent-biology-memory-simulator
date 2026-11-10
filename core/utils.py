import os
import json
import tempfile
import time
import threading
from contextlib import nullcontext


# Windows may reject simultaneous os.replace calls for the same destination.
# A fixed-size stripe table provides per-path serialization without an
# unbounded dictionary of locks. Callers sharing a target across processes
# still rely on Aura's writer lease; unique names keep temp files independent.
_ATOMIC_WRITE_LOCKS = tuple(threading.Lock() for _ in range(64))


def _windows_extended_path(path, *, force=False):
    """Return a Win32 extended-length path when ``path`` needs one.

    Python's normal Windows paths still depend on the machine-wide
    ``LongPathsEnabled`` policy for operations such as ``os.replace``.  Aura
    cannot assume that policy is enabled on every workstation.  The Win32
    extended-length namespace opts this individual operation into the wide
    path API instead.

    Keep ordinary paths unchanged so callers, mocks, and diagnostics retain
    their established short-path behaviour.  ``bytes`` paths are also left
    alone because the extended-length namespace is a Unicode API contract.
    """
    if os.name != "nt" or isinstance(path, bytes):
        return path

    absolute = os.path.abspath(path)
    if absolute.startswith("\\\\?\\") or (not force and len(absolute) < 248):
        return absolute
    if absolute.startswith("\\\\"):
        return "\\\\?\\UNC\\" + absolute[2:]
    return "\\\\?\\" + absolute


def _atomic_write_lock(file_path):
    if os.name != "nt":
        # POSIX replace permits concurrent publishers. Avoid carrying a
        # possibly held process-local lock into a forked child.
        return nullcontext()
    normalized = os.path.normcase(os.path.abspath(file_path))
    return _ATOMIC_WRITE_LOCKS[hash(normalized) % len(_ATOMIC_WRITE_LOCKS)]


def _fsync_directory(directory):
    """Best-effort durability for a rename on platforms that support it."""
    if os.name == "nt":
        return

    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    try:
        fd = os.open(directory, flags)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        # Some filesystems do not support syncing directories. The file itself
        # has already been synced and published, so this remains best-effort.
        pass
    finally:
        try:
            os.close(fd)
        except OSError:
            pass

def atomic_read_json(file_path):
    """Đọc file JSON một cách an toàn."""
    read_path = _windows_extended_path(os.fspath(file_path))
    with open(read_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def _replace_with_retry(source, destination, attempts=6):
    """os.replace that rides out transient Windows sharing violations.

    Antivirus/indexer services briefly open a file right after it is written;
    replacing it during that window fails with "Access is denied" although
    nothing in this process holds it. Back off a few milliseconds and retry.
    """
    for attempt in range(attempts):
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if os.name != "nt" or attempt == attempts - 1:
                raise
            time.sleep(0.005 * (2 ** attempt))


def atomic_write_json(file_path, data):
    """Ghi file JSON một cách nguyên tử (atomic) để tránh file bị rỗng/lỗi khi crash."""
    # Validate the complete value before creating a directory or touching the
    # previous checkpoint. Stable key ordering makes the on-disk form suitable
    # for deterministic audits and hashes. NaN/Infinity are not JSON values.
    serialized = json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")

    raw_path = os.fspath(file_path)
    if not raw_path:
        raise ValueError("file_path must not be empty")
    target_path = os.path.abspath(raw_path)
    dirpath = os.path.dirname(target_path)
    if not os.path.basename(target_path):
        raise ValueError("file_path must name a file")

    # The generic, bounded prefix avoids both fixed-name collisions and name-
    # length failures when a destination basename is already near the limit.
    # mkstemp uses O_EXCL in the target directory, keeping replace atomic.
    with _atomic_write_lock(target_path):
        io_target_path = _windows_extended_path(target_path)
        target_uses_extended_namespace = (
            isinstance(io_target_path, str)
            and io_target_path.startswith("\\\\?\\")
        )
        # A target can exceed MAX_PATH because its directory is already near
        # the limit even when that directory alone is shorter than 248 chars.
        # Force the same namespace for mkstemp so its generated filename does
        # not push the staging path back over the legacy limit.
        io_dirpath = _windows_extended_path(
            dirpath,
            force=target_uses_extended_namespace,
        )
        os.makedirs(io_dirpath, exist_ok=True)
        prefix = b".tmp-json-" if isinstance(target_path, bytes) else ".tmp-json-"
        suffix = b".tmp" if isinstance(target_path, bytes) else ".tmp"
        fd, temp_path = tempfile.mkstemp(prefix=prefix, suffix=suffix, dir=io_dirpath)
        try:
            with os.fdopen(fd, "wb") as stream:
                fd = None
                stream.write(serialized)
                stream.flush()
                os.fsync(stream.fileno())
            _replace_with_retry(temp_path, io_target_path)
            _fsync_directory(io_dirpath)
        finally:
            try:
                if fd is not None:
                    os.close(fd)
            finally:
                try:
                    os.unlink(temp_path)
                except FileNotFoundError:
                    pass

def atomic_write_text(file_path, text):
    """Atomically publish UTF-8 text without exposing partial contents."""
    # Encode before performing any filesystem operation. Besides making the
    # exact byte representation explicit, this ensures invalid values cannot
    # create a directory or disturb the previous document.
    serialized = text.encode("utf-8")

    raw_path = os.fspath(file_path)
    if not raw_path:
        raise ValueError("file_path must not be empty")
    target_path = os.path.abspath(raw_path)
    dirpath = os.path.dirname(target_path)
    if not os.path.basename(target_path):
        raise ValueError("file_path must name a file")

    with _atomic_write_lock(target_path):
        io_target_path = _windows_extended_path(target_path)
        target_uses_extended_namespace = (
            isinstance(io_target_path, str)
            and io_target_path.startswith("\\\\?\\")
        )
        # A short directory can still yield an over-MAX_PATH staging filename.
        # Use the target's namespace decision for the unique sibling temp too.
        io_dirpath = _windows_extended_path(
            dirpath,
            force=target_uses_extended_namespace,
        )
        os.makedirs(io_dirpath, exist_ok=True)
        prefix = b".tmp-text-" if isinstance(target_path, bytes) else ".tmp-text-"
        suffix = b".tmp" if isinstance(target_path, bytes) else ".tmp"
        fd, temp_path = tempfile.mkstemp(prefix=prefix, suffix=suffix, dir=io_dirpath)
        try:
            with os.fdopen(fd, "wb") as stream:
                fd = None
                stream.write(serialized)
                stream.flush()
                os.fsync(stream.fileno())
            _replace_with_retry(temp_path, io_target_path)
            _fsync_directory(io_dirpath)
        finally:
            try:
                if fd is not None:
                    os.close(fd)
            finally:
                try:
                    os.unlink(temp_path)
                except FileNotFoundError:
                    pass
