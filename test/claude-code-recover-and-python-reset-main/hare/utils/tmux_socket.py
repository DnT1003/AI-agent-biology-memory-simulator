"""Isolated tmux socket for Claude (port of tmuxSocket.ts)."""

from __future__ import annotations

import os
from typing import Any

from hare.utils.debug import log_for_debugging
from hare.utils.exec_file_no_throw import exec_file_no_throw
from hare.utils.platform import get_platform

TMUX_COMMAND = "tmux"
CLAUDE_SOCKET_PREFIX = "claude"

_socket_name: str | None = None
_socket_path: str | None = None
_server_pid: int | None = None
_is_initializing = False
_init_promise: Any = None
_tmux_availability_checked = False
_tmux_available = False
_tmux_tool_used = False


def get_claude_socket_name() -> str:
    global _socket_name
    if _socket_name is None:
        _socket_name = f"{CLAUDE_SOCKET_PREFIX}-{os.getpid()}"
    return _socket_name


def get_claude_socket_path() -> str | None:
    return _socket_path


def set_claude_socket_info(path: str, pid: int) -> None:
    global _socket_path, _server_pid
    _socket_path = path
    _server_pid = pid


def is_socket_initialized() -> bool:
    return _socket_path is not None and _server_pid is not None


def get_claude_tmux_env() -> str | None:
    if not _socket_path or _server_pid is None:
        return None
    return f"{_socket_path},{_server_pid},0"


async def check_tmux_available() -> bool:
    global _tmux_availability_checked, _tmux_available
    if not _tmux_availability_checked:
        if get_platform() == "windows":
            r = await exec_file_no_throw(
                "wsl",
                ["-e", TMUX_COMMAND, "-V"],
                {"env": {**os.environ, "WSL_UTF8": "1"}, "use_cwd": False},
            )
        else:
            r = await exec_file_no_throw("which", [TMUX_COMMAND], {"use_cwd": False})
        _tmux_available = r.get("code") == 0
        if not _tmux_available:
            log_for_debugging(
                "[Socket] tmux is not installed. The Tmux tool and Teammate tool will not be available."
            )
        _tmux_availability_checked = True
    return _tmux_available


def is_tmux_available() -> bool:
    return _tmux_availability_checked and _tmux_available


def mark_tmux_tool_used() -> None:
    global _tmux_tool_used
    _tmux_tool_used = True


def has_tmux_tool_been_used() -> bool:
    return _tmux_tool_used


async def ensure_socket_initialized() -> None:
    if is_socket_initialized():
        return
    if not await check_tmux_available():
        return
    # Full session creation matches TS doInitialize — wire subprocess tmux -L …
    log_for_debugging("[Socket] ensure_socket_initialized: stub (no tmux session created)")


async def kill_tmux_server() -> None:
    sock = get_claude_socket_name()
    log_for_debugging(f"[Socket] Killing tmux server for socket: {sock}")
    await exec_file_no_throw(
        TMUX_COMMAND, ["-L", sock, "kill-server"], {"use_cwd": False}
    )


def reset_socket_state() -> None:
    global _socket_name, _socket_path, _server_pid, _is_initializing, _init_promise
    global _tmux_availability_checked, _tmux_available, _tmux_tool_used
    _socket_name = None
    _socket_path = None
    _server_pid = None
    _is_initializing = False
    _init_promise = None
    _tmux_availability_checked = False
    _tmux_available = False
    _tmux_tool_used = False
