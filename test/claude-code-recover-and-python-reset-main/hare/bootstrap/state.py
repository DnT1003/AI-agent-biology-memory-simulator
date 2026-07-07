"""
Global bootstrap state – session ID, project root, flags.

Port of: src/bootstrap/state.ts
"""

from __future__ import annotations

import os
from typing import Callable, Optional
from uuid import uuid4

from hare.types.ids import SessionId, as_session_id

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

_session_id: SessionId = as_session_id(str(uuid4()))
_project_root: str = os.getcwd()
_original_cwd: str = os.getcwd()
_is_non_interactive: bool = False
_session_persistence_disabled: bool = False


def get_session_id() -> str:
    return _session_id


_session_switch_callbacks: list[Callable[[SessionId], None]] = []


def on_session_switch(cb: Callable[[SessionId], None]) -> None:
    """Register a callback invoked when the session id changes (e.g. --resume)."""
    _session_switch_callbacks.append(cb)


def switch_session(new_id: SessionId) -> None:
    global _session_id
    _session_id = new_id
    for fn in _session_switch_callbacks:
        fn(new_id)


def get_project_root() -> str:
    return _project_root


def set_project_root(path: str) -> None:
    global _project_root
    _project_root = path


def get_original_cwd() -> str:
    return _original_cwd


def set_original_cwd(path: str) -> None:
    global _original_cwd
    _original_cwd = path


def get_is_non_interactive_session() -> bool:
    return _is_non_interactive


def set_is_non_interactive_session(value: bool) -> None:
    global _is_non_interactive
    _is_non_interactive = value


def is_session_persistence_disabled() -> bool:
    return _session_persistence_disabled


def set_session_persistence_disabled(value: bool) -> None:
    global _session_persistence_disabled
    _session_persistence_disabled = value


# ---------------------------------------------------------------------------
# CWD state (for tools and config)
# ---------------------------------------------------------------------------

_cwd: str = os.getcwd()


def get_cwd() -> str:
    return _cwd


def set_cwd(path: str) -> None:
    global _cwd
    _cwd = path


def set_cwd_state(path: str) -> None:
    """Alias for set_cwd, matches TS setCwdState."""
    set_cwd(path)


# ---------------------------------------------------------------------------
# Plugin / cowork mode (port of src/bootstrap/state.ts flags)
# ---------------------------------------------------------------------------

_use_cowork_plugins: bool = False


def get_use_cowork_plugins() -> bool:
    """True when --cowork set session state for cowork_plugins dir."""
    return _use_cowork_plugins


def set_use_cowork_plugins(value: bool) -> None:
    global _use_cowork_plugins
    _use_cowork_plugins = value
