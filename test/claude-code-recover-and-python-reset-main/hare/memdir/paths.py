"""Auto-memory path resolution (port of src/memdir/paths.ts)."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


def _env_truthy(val: str | None) -> bool:
    if not val:
        return False
    return val.lower() in ("1", "true", "yes")


def is_auto_memory_enabled() -> bool:
    if _env_truthy(os.environ.get("CLAUDE_CODE_DISABLE_AUTO_MEMORY")):
        return False
    if _env_truthy(os.environ.get("CLAUDE_CODE_SIMPLE")):
        return False
    if _env_truthy(os.environ.get("CLAUDE_CODE_REMOTE")) and not os.environ.get(
        "CLAUDE_CODE_REMOTE_MEMORY_DIR"
    ):
        return False
    return True


def get_memory_base_dir() -> str:
    return os.environ.get("CLAUDE_CODE_REMOTE_MEMORY_DIR") or str(
        Path.home() / ".claude"
    )


@lru_cache(maxsize=1)
def get_auto_mem_path() -> str:
    override = os.environ.get("CLAUDE_COWORK_MEMORY_PATH_OVERRIDE")
    if override:
        p = Path(override)
        return str(p if str(p).endswith(os.sep) else p / "")  # trailing sep contract
    base = get_memory_base_dir()
    # Stub project key — wire to git root / project root when integrated
    project_key = os.environ.get("CLAUDE_PROJECT_KEY", "default")
    return str(Path(base) / "projects" / project_key / "memory") + os.sep


def get_auto_mem_entrypoint() -> str:
    return str(Path(get_auto_mem_path()) / "MEMORY.md")


def get_auto_mem_daily_log_path(date: object | None = None) -> str:
    import datetime

    d = date or datetime.datetime.now()
    if not isinstance(d, datetime.datetime):
        d = datetime.datetime.now()
    y, m, day = d.year, d.month, d.day
    return str(
        Path(get_auto_mem_path())
        / "logs"
        / str(y)
        / f"{m:02d}"
        / f"{y}-{m:02d}-{day:02d}.md"
    )


def is_auto_mem_path(absolute_path: str) -> bool:
    return os.path.normpath(absolute_path).startswith(os.path.normpath(get_auto_mem_path()))


def has_auto_mem_path_override() -> bool:
    return bool(os.environ.get("CLAUDE_COWORK_MEMORY_PATH_OVERRIDE"))
