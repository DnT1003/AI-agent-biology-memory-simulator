import os
import json
import shutil
import tempfile
import threading
from contextlib import nullcontext


# Windows may reject simultaneous os.replace calls for the same destination.
# A fixed-size stripe table provides per-path serialization without an
# unbounded dictionary of locks. Callers sharing a target across processes
# still rely on Aura's writer lease; unique names keep temp files independent.
_ATOMIC_WRITE_LOCKS = tuple(threading.Lock() for _ in range(64))


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
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)

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
        os.makedirs(dirpath, exist_ok=True)
        prefix = b".tmp-json-" if isinstance(target_path, bytes) else ".tmp-json-"
        suffix = b".tmp" if isinstance(target_path, bytes) else ".tmp"
        fd, temp_path = tempfile.mkstemp(prefix=prefix, suffix=suffix, dir=dirpath)
        try:
            with os.fdopen(fd, "wb") as stream:
                fd = None
                stream.write(serialized)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, target_path)
            _fsync_directory(dirpath)
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
    """Ghi file text một cách nguyên tử."""
    temp_path = file_path + ".tmp"
    try:
        dirpath = os.path.dirname(file_path)
        if dirpath:
            os.makedirs(dirpath, exist_ok=True)
        with open(temp_path, 'w', encoding='utf-8') as f:
            f.write(text)
        shutil.move(temp_path, file_path)
    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise e
