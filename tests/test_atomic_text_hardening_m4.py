import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from core import utils


ROOT = Path(__file__).resolve().parents[1]


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
        raise _WriteAbort("simulated interruption")


class AtomicWriteTextHardeningM4Tests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(dir=ROOT)
        self.root = Path(self.temp_dir.name)
        self.target = self.root / "state.txt"
        self.target.write_text("old", encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def _assert_no_temps(self):
        self.assertEqual(list(self.root.glob(".tmp-text-*.tmp")), [])

    def test_pathlike_writes_utf8_and_leaves_no_staging_file(self):
        utils.atomic_write_text(self.target, "Tiếng Việt: cà phê ☕")

        self.assertEqual(
            self.target.read_bytes(),
            "Tiếng Việt: cà phê ☕".encode("utf-8"),
        )
        self._assert_no_temps()

    def test_replace_failure_preserves_old_target_and_removes_exact_temp(self):
        with patch("core.utils.os.replace", side_effect=OSError("replace failed")):
            with self.assertRaisesRegex(OSError, "replace failed"):
                utils.atomic_write_text(os.fspath(self.target), "new")

        self.assertEqual(self.target.read_text(encoding="utf-8"), "old")
        self._assert_no_temps()

    def test_baseexception_preserves_old_target_and_removes_exact_temp(self):
        real_fdopen = os.fdopen

        def failing_fdopen(*args, **kwargs):
            return _FailingStream(real_fdopen(*args, **kwargs))

        with patch("core.utils.os.fdopen", side_effect=failing_fdopen):
            with self.assertRaisesRegex(_WriteAbort, "simulated interruption"):
                utils.atomic_write_text(self.target, "new")

        self.assertEqual(self.target.read_text(encoding="utf-8"), "old")
        self._assert_no_temps()

    def test_unrelated_legacy_fixed_temp_is_untouched(self):
        unrelated = Path(os.fspath(self.target) + ".tmp")
        unrelated.write_text("another writer", encoding="utf-8")

        utils.atomic_write_text(self.target, "new")

        self.assertEqual(unrelated.read_text(encoding="utf-8"), "another writer")
        self._assert_no_temps()

    @unittest.skipUnless(os.name == "nt", "Win32 extended paths are Windows-specific")
    def test_total_path_over_max_path_writes_reads_and_cleans_up(self):
        target = self.root / (("long-text-" + ("x" * 190)) + ".txt")
        self.assertGreater(len(os.path.abspath(target)), 260)

        try:
            utils.atomic_write_text(target, "complete ✓")
            io_target = utils._windows_extended_path(os.fspath(target))
            with open(io_target, "r", encoding="utf-8") as stream:
                self.assertEqual(stream.read(), "complete ✓")
            self._assert_no_temps()
        finally:
            try:
                os.unlink(utils._windows_extended_path(os.fspath(target)))
            except FileNotFoundError:
                pass

    def test_concurrent_publishers_leave_one_complete_document(self):
        count = 16
        barrier = threading.Barrier(count)
        failures = []
        failures_lock = threading.Lock()
        payloads = [f"writer={index}\n" + (str(index) * 8_000) for index in range(count)]

        def write(index):
            try:
                barrier.wait(timeout=5)
                utils.atomic_write_text(self.target, payloads[index])
            except BaseException as exc:
                with failures_lock:
                    failures.append(exc)

        threads = [threading.Thread(target=write, args=(index,)) for index in range(count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(failures, [])
        self.assertIn(self.target.read_text(encoding="utf-8"), payloads)
        self._assert_no_temps()


if __name__ == "__main__":
    unittest.main()
