"""Project-scoped cache directory paths (`cachePaths.ts`)."""

from __future__ import annotations

import os
import re
from functools import lru_cache

from hare.utils.hash import djb2_hash


MAX_SANITIZED_LENGTH = 200


def _sanitize_path(name: str) -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9]", "-", name)
    if len(sanitized) <= MAX_SANITIZED_LENGTH:
        return sanitized
    h = abs(djb2_hash(name))
    return f"{sanitized[:MAX_SANITIZED_LENGTH]}-{h:x}"


@lru_cache(maxsize=1)
def _env_paths_cache() -> str:
    """Return base cache dir for `claude-cli` (stub: platformdirs/env)."""
    try:
        import platformdirs

        return platformdirs.user_cache_dir("claude-cli", appauthor=False)
    except ImportError:
        return os.path.join(os.path.expanduser("~"), ".cache", "claude-cli")


def _project_dir(cwd: str) -> str:
    return _sanitize_path(cwd)


class CachePaths:
    @staticmethod
    def base_logs() -> str:
        base = _env_paths_cache()
        cwd = os.getcwd()
        return os.path.join(base, _project_dir(cwd))

    @staticmethod
    def errors() -> str:
        return os.path.join(CachePaths.base_logs(), "errors")

    @staticmethod
    def messages() -> str:
        return os.path.join(CachePaths.base_logs(), "messages")

    @staticmethod
    def mcp_logs(server_name: str) -> str:
        safe = _sanitize_path(server_name)
        return os.path.join(CachePaths.base_logs(), f"mcp-logs-{safe}")


CACHE_PATHS = CachePaths
