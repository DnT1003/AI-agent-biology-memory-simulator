"""Process warning hooks (port of warningHandler.ts)."""

from __future__ import annotations

import logging

MAX_WARNING_KEYS = 1000


def reset_warning_handler() -> None:
    pass


def initialize_warning_handler() -> None:
    """Route Python warnings through logging (stub for Node process.on('warning'))."""
    logging.captureWarnings(True)
