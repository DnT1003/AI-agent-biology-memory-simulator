"""
OpenTelemetry DiagLogger bridge.

Port of: src/utils/telemetry/logger.ts
"""

from __future__ import annotations


class ClaudeCodeDiagLogger:
    """Maps OTEL diag callbacks to application logging (stub)."""

    def error(self, message: str, *_args: object) -> None:
        del _args
        _ = message

    def warn(self, message: str, *_args: object) -> None:
        del _args
        _ = message

    def info(self, _message: str, *_args: object) -> None:
        return

    def debug(self, _message: str, *_args: object) -> None:
        return

    def verbose(self, _message: str, *_args: object) -> None:
        return
