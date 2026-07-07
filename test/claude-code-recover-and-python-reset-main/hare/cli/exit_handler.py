"""Port of: src/cli/exit.ts"""
from __future__ import annotations
import sys

def handle_exit(code: int = 0) -> None:
    sys.exit(code)

def setup_exit_handlers() -> None:
    import atexit, signal
    atexit.register(lambda: None)
