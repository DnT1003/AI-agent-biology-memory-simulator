"""
Backend registry – detects and caches the appropriate pane backend.

Port of: src/utils/swarm/backends/registry.ts
"""

from __future__ import annotations

import os
import shutil
from typing import Any

from hare.utils.swarm.backends.types import (
    BackendDetectionResult,
    PaneBackend,
    PaneBackendType,
    TeammateExecutor,
)

_cached_backend: PaneBackend | None = None
_cached_detection: BackendDetectionResult | None = None
_in_process_fallback: bool = False


def _is_inside_tmux() -> bool:
    return bool(os.environ.get("TMUX"))


def _is_in_iterm2() -> bool:
    return os.environ.get("TERM_PROGRAM") == "iTerm.app"


def _is_tmux_available() -> bool:
    return shutil.which("tmux") is not None


async def detect_and_get_backend() -> BackendDetectionResult:
    global _cached_backend, _cached_detection
    if _cached_detection:
        return _cached_detection

    if _is_inside_tmux():
        backend = _TmuxBackendStub()
        _cached_backend = backend
        _cached_detection = BackendDetectionResult(backend=backend, is_native=True)
        return _cached_detection

    if _is_in_iterm2():
        if _is_tmux_available():
            backend = _TmuxBackendStub()
            _cached_backend = backend
            _cached_detection = BackendDetectionResult(backend=backend, is_native=False, needs_it2_setup=True)
            return _cached_detection
        raise RuntimeError("iTerm2 detected but no tmux available. Install tmux: brew install tmux")

    if _is_tmux_available():
        backend = _TmuxBackendStub()
        _cached_backend = backend
        _cached_detection = BackendDetectionResult(backend=backend, is_native=False)
        return _cached_detection

    raise RuntimeError("No pane backend available. Install tmux to use agent swarms.")


def get_backend_by_type(backend_type: PaneBackendType) -> PaneBackend:
    if backend_type == "tmux":
        return _TmuxBackendStub()
    return _ITermBackendStub()


def is_in_process_enabled() -> bool:
    global _in_process_fallback
    mode = os.environ.get("CLAUDE_TEAMMATE_MODE", "auto")
    if mode == "in-process":
        return True
    if mode == "tmux":
        return False
    if _in_process_fallback:
        return True
    return not _is_inside_tmux() and not _is_in_iterm2()


def get_resolved_teammate_mode() -> str:
    return "in-process" if is_in_process_enabled() else "tmux"


def mark_in_process_fallback() -> None:
    global _in_process_fallback
    _in_process_fallback = True


def get_in_process_backend() -> TeammateExecutor:
    return _InProcessExecutorStub()


async def get_teammate_executor(prefer_in_process: bool = False) -> TeammateExecutor:
    if prefer_in_process and is_in_process_enabled():
        return get_in_process_backend()
    return _PaneExecutorStub()


def reset_backend_detection() -> None:
    global _cached_backend, _cached_detection, _in_process_fallback
    _cached_backend = None
    _cached_detection = None
    _in_process_fallback = False


class _TmuxBackendStub(PaneBackend):
    @property
    def type(self) -> PaneBackendType:
        return "tmux"

    async def create_pane(self, command: str, cwd: str) -> str:
        return "tmux-pane-stub"

    async def kill_pane(self, pane_id: str) -> None:
        pass

    async def send_keys(self, pane_id: str, keys: str) -> None:
        pass


class _ITermBackendStub(PaneBackend):
    @property
    def type(self) -> PaneBackendType:
        return "iterm2"

    async def create_pane(self, command: str, cwd: str) -> str:
        return "iterm2-pane-stub"

    async def kill_pane(self, pane_id: str) -> None:
        pass

    async def send_keys(self, pane_id: str, keys: str) -> None:
        pass


class _InProcessExecutorStub(TeammateExecutor):
    async def spawn(self, config: dict[str, Any]) -> dict[str, Any]:
        return {"agent_id": "in-process-stub"}

    async def stop(self, agent_id: str) -> None:
        pass


class _PaneExecutorStub(TeammateExecutor):
    async def spawn(self, config: dict[str, Any]) -> dict[str, Any]:
        return {"agent_id": "pane-stub"}

    async def stop(self, agent_id: str) -> None:
        pass
