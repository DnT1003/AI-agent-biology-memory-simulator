"""
Environment probes that need subprocess or native feature flags.

Port of: src/utils/envDynamic.ts
"""

from __future__ import annotations

import os
import platform
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from hare.utils.env import JETBRAINS_IDES, env
from hare.utils.env_utils import is_env_truthy
from hare.utils.exec_file_no_throw import exec_file_no_throw

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


def _feature(name: str) -> bool:
    """Native build feature flags; stub via env `FEATURE_<NAME>`."""
    return os.environ.get(f"FEATURE_{name}") == "1"


_musl_runtime_cache: bool | None = None


def _prime_musl_cache() -> None:
    global _musl_runtime_cache
    if platform.system() != "Linux":
        return
    arch = platform.machine()
    musl_arch = "x86_64" if arch in ("x86_64", "AMD64") else "aarch64"
    p = Path(f"/lib/libc.musl-{musl_arch}.so.1")

    def _set() -> None:
        global _musl_runtime_cache
        _musl_runtime_cache = p.is_file()

    threading.Thread(target=_set, daemon=True).start()


if platform.system() == "Linux":
    _prime_musl_cache()


async def get_is_docker() -> bool:
    if platform.system() != "Linux":
        return False
    r = await exec_file_no_throw("test", ["-f", "/.dockerenv"])
    return r["code"] == 0


def get_is_bubblewrap_sandbox() -> bool:
    return platform.system() == "Linux" and is_env_truthy(
        os.environ.get("CLAUDE_CODE_BUBBLEWRAP")
    )


def is_musl_environment() -> bool:
    if _feature("IS_LIBC_MUSL"):
        return True
    if _feature("IS_LIBC_GLIBC"):
        return False
    if platform.system() != "Linux":
        return False
    return bool(_musl_runtime_cache)


_UNSET = object()
_jetbrains_ide_cache: str | None | object = _UNSET


async def _detect_jetbrains_ide_from_parent_process_async() -> str | None:
    global _jetbrains_ide_cache
    if _jetbrains_ide_cache is not _UNSET:
        return None if _jetbrains_ide_cache is None else str(_jetbrains_ide_cache)

    if platform.system() == "darwin":
        _jetbrains_ide_cache = None
        return None

    from hare.utils.generic_process_utils import get_ancestor_commands_async

    try:
        commands = await get_ancestor_commands_async(os.getpid(), 10)
        for command in commands:
            lower = command.lower()
            for ide in JETBRAINS_IDES:
                if ide in lower:
                    _jetbrains_ide_cache = ide
                    return ide
    except OSError:
        pass
    _jetbrains_ide_cache = None
    return None


async def get_terminal_with_jetbrains_detection_async() -> str | None:
    if os.environ.get("TERMINAL_EMULATOR") == "JetBrains-JediTerm":
        if env.platform != "darwin":
            specific = await _detect_jetbrains_ide_from_parent_process_async()
            return specific or "pycharm"
    return env.terminal


def get_terminal_with_jetbrains_detection() -> str | None:
    if os.environ.get("TERMINAL_EMULATOR") == "JetBrains-JediTerm":
        if env.platform != "darwin":
            if _jetbrains_ide_cache is not _UNSET:
                return _jetbrains_ide_cache or "pycharm"
            return "pycharm"
    return env.terminal


async def init_jetbrains_detection() -> None:
    if os.environ.get("TERMINAL_EMULATOR") == "JetBrains-JediTerm":
        await _detect_jetbrains_ide_from_parent_process_async()


class EnvDynamicNamespace:
    has_internet_access = env.has_internet_access
    is_ci = env.is_ci
    platform = env.platform
    arch = env.arch
    node_version = env.node_version
    terminal = get_terminal_with_jetbrains_detection()
    is_ssh = env.is_ssh
    get_package_managers = env.get_package_managers
    get_runtimes = env.get_runtimes
    is_running_with_bun = env.is_running_with_bun
    is_wsl_environment = env.is_wsl_environment
    is_npm_from_windows_path = env.is_npm_from_windows_path
    is_conductor = env.is_conductor
    detect_deployment_environment = env.detect_deployment_environment
    get_is_docker = staticmethod(get_is_docker)
    get_is_bubblewrap_sandbox = staticmethod(get_is_bubblewrap_sandbox)
    is_musl_environment = staticmethod(is_musl_environment)
    get_terminal_with_jetbrains_detection_async = staticmethod(
        get_terminal_with_jetbrains_detection_async
    )
    init_jetbrains_detection = staticmethod(init_jetbrains_detection)


env_dynamic = EnvDynamicNamespace()
