import json
import math
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from core import utils


class _WriteAbort(BaseException):
    pass


class _FailingStream:
    def __init__(self, stream):
        self._stream = stream

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self._stream.close()
        return False

    def write(self, _data):
        raise _WriteAbort("simulated crash while writing")


class AtomicWriteJsonM3Tests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.target = self.root / "state.json"
        self.target.write_text('{"old":true}', encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def _assert_no_temps(self):
        self.assertEqual(list(self.root.glob(".tmp-json-*.tmp")), [])

    def test_serialization_is_stable_utf8_and_rejects_nan_before_io(self):
        utils.atomic_write_json(self.target, {"z": 1, "a": "café"})
        self.assertEqual(self.target.read_bytes(), '{"a":"café","z":1}'.encode("utf-8"))

        previous = self.target.read_bytes()
        with self.assertRaises(ValueError):
            utils.atomic_write_json(self.target, {"nested": [math.nan]})
        self.assertEqual(self.target.read_bytes(), previous)
        self._assert_no_temps()

    def test_replace_failure_preserves_target_and_removes_exact_temp(self):
        with patch("core.utils.os.replace", side_effect=OSError("replace failed")):
            with self.assertRaisesRegex(OSError, "replace failed"):
                utils.atomic_write_json(self.target, {"new": True})

        self.assertEqual(json.loads(self.target.read_text(encoding="utf-8")), {"old": True})
        self._assert_no_temps()

    def test_legacy_fixed_temp_name_is_never_touched(self):
        unrelated = Path(str(self.target) + ".tmp")
        unrelated.write_bytes(b"belongs to another writer")

        utils.atomic_write_json(self.target, {"new": True})

        self.assertEqual(unrelated.read_bytes(), b"belongs to another writer")
        self._assert_no_temps()

    def test_file_fsync_failure_preserves_target_and_removes_temp(self):
        with patch("core.utils.os.fsync", side_effect=OSError("fsync failed")):
            with self.assertRaisesRegex(OSError, "fsync failed"):
                utils.atomic_write_json(self.target, {"new": True})

        self.assertEqual(json.loads(self.target.read_text(encoding="utf-8")), {"old": True})
        self._assert_no_temps()

    def test_baseexception_during_write_preserves_target_and_removes_temp(self):
        real_fdopen = os.fdopen

        def failing_fdopen(*args, **kwargs):
            return _FailingStream(real_fdopen(*args, **kwargs))

        with patch("core.utils.os.fdopen", side_effect=failing_fdopen):
            with self.assertRaisesRegex(_WriteAbort, "simulated crash"):
                utils.atomic_write_json(self.target, {"new": True})

        self.assertEqual(json.loads(self.target.read_text(encoding="utf-8")), {"old": True})
        self._assert_no_temps()

    def test_directory_fsync_is_best_effort_and_closes_descriptor(self):
        with patch.object(utils.os, "name", "posix"), patch(
            "core.utils.os.open", return_value=37
        ) as open_mock, patch(
            "core.utils.os.fsync", side_effect=OSError("unsupported")
        ) as fsync_mock, patch("core.utils.os.close") as close_mock:
            utils._fsync_directory(str(self.root))

        open_mock.assert_called_once()
        fsync_mock.assert_called_once_with(37)
        close_mock.assert_called_once_with(37)

    def test_long_destination_name_does_not_expand_temp_prefix(self):
        target = self.root / (("x" * 220) + ".json")
        try:
            utils.atomic_write_json(target, {"ok": True})
            self.assertEqual(utils.atomic_read_json(target), {"ok": True})
            self._assert_no_temps()
        finally:
            # Machines without the LongPathsEnabled policy also need the
            # explicit Win32 namespace for test cleanup.
            try:
                os.unlink(utils._windows_extended_path(os.fspath(target)))
            except FileNotFoundError:
                pass

    def test_concurrent_writers_publish_only_complete_documents(self):
        count = 16
        barrier = threading.Barrier(count)
        failures = []
        failures_lock = threading.Lock()

        def write(index):
            try:
                barrier.wait(timeout=5)
                utils.atomic_write_json(
                    self.target,
                    {"writer": index, "values": [index] * 2_000},
                )
            except BaseException as exc:  # surfaced in the owning test thread
                with failures_lock:
                    failures.append(exc)

        threads = [threading.Thread(target=write, args=(index,)) for index in range(count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(failures, [])
        persisted = json.loads(self.target.read_text(encoding="utf-8"))
        self.assertIn(persisted["writer"], range(count))
        self.assertEqual(persisted["values"], [persisted["writer"]] * 2_000)
        self._assert_no_temps()


if __name__ == "__main__":
    unittest.main()
