from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path


class EventJournalConfigTests(unittest.TestCase):
    def test_invalid_optional_journal_limits_do_not_break_config_import(self):
        project_root = Path(__file__).resolve().parents[1]
        environment = os.environ.copy()
        environment.update(
            {
                "AURA_EVENT_JOURNAL_MAX_EVENTS": "not-an-int",
                "AURA_EVENT_JOURNAL_MAX_EVENT_BYTES": "also-invalid",
                "AURA_EVENT_JOURNAL_LOCK_TIMEOUT_SECONDS": "NaN",
            }
        )

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "from config import Config; "
                    "print(Config.EVENT_JOURNAL_MAX_EVENTS, "
                    "Config.EVENT_JOURNAL_MAX_EVENT_BYTES, "
                    "Config.EVENT_JOURNAL_LOCK_TIMEOUT_SECONDS)"
                ),
            ],
            cwd=project_root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "100000 65536 1.0")

    def test_journal_limits_are_clamped_to_safe_minima(self):
        project_root = Path(__file__).resolve().parents[1]
        environment = os.environ.copy()
        environment.update(
            {
                "AURA_EVENT_JOURNAL_MAX_EVENTS": "0",
                "AURA_EVENT_JOURNAL_MAX_EVENT_BYTES": "-4",
                "AURA_EVENT_JOURNAL_LOCK_TIMEOUT_SECONDS": "-inf",
            }
        )

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "from config import Config; "
                    "print(Config.EVENT_JOURNAL_MAX_EVENTS, "
                    "Config.EVENT_JOURNAL_MAX_EVENT_BYTES, "
                    "Config.EVENT_JOURNAL_LOCK_TIMEOUT_SECONDS)"
                ),
            ],
            cwd=project_root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "1 1024 1.0")


if __name__ == "__main__":
    unittest.main()
