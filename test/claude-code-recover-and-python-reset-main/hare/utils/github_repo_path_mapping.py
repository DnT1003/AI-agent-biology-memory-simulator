"""
Global config: GitHub repo slug → known local clone paths.

Port of: src/utils/githubRepoPathMapping.ts
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Awaitable, Callable

from hare.utils.debug import log_for_debugging

_get_original_cwd: Callable[[], str] = lambda: os.getcwd()
_get_global_config: Callable[[], dict[str, Any]] = lambda: {}
_save_global_config: Callable[[Callable[[dict[str, Any]], dict[str, Any]]], None] = lambda _f: None
_detect_current_repository: Callable[[], str | None | Awaitable[str | None]] = lambda: None
_parse_github_repository: Callable[[str], str | None] = lambda _u: None
_get_remote_url_for_dir: Callable[[str], str | None | Awaitable[str | None]] = lambda _p: None
_find_git_root: Callable[[str], str | None] = lambda c: c


def configure_github_repo_mapping_hooks(**kwargs: Any) -> None:
    for k, v in kwargs.items():
        globals()[k] = v


async def path_exists(p: str) -> bool:
    return Path(p).exists()


async def update_github_repo_path_mapping() -> None:
    try:
        repo = _detect_current_repository()
        if hasattr(repo, "__await__"):
            repo = await repo  # type: ignore[assignment]
        if not repo:
            log_for_debugging("Not in a GitHub repository, skipping path mapping update")
            return
        cwd = _get_original_cwd()
        git_root = _find_git_root(cwd)
        base_path = git_root or cwd
        try:
            current_path = str(Path(base_path).resolve())
        except OSError:
            current_path = base_path
        repo_key = str(repo).lower()
        config = _get_global_config()
        paths_map = dict(config.get("githubRepoPaths") or {})
        existing = list(paths_map.get(repo_key, []))
        if existing[:1] == [current_path]:
            log_for_debugging(f"Path {current_path} already tracked for repo {repo_key}")
            return
        without = [p for p in existing if p != current_path]
        paths_map[repo_key] = [current_path, *without]

        def _merge(c: dict[str, Any]) -> dict[str, Any]:
            return {**c, "githubRepoPaths": paths_map}

        _save_global_config(_merge)
        log_for_debugging(f"Added {current_path} to tracked paths for repo {repo_key}")
    except Exception as e:  # noqa: BLE001
        log_for_debugging(f"Error updating repo path mapping: {e}")


def get_known_paths_for_repo(repo: str) -> list[str]:
    repo_key = repo.lower()
    cfg = _get_global_config()
    return list((cfg.get("githubRepoPaths") or {}).get(repo_key, []))


async def filter_existing_paths(paths: list[str]) -> list[str]:
    import asyncio

    results = await asyncio.gather(*[path_exists(p) for p in paths])
    return [p for p, ok in zip(paths, results, strict=True) if ok]


async def validate_repo_at_path(path: str, expected_repo: str) -> bool:
    try:
        url = _get_remote_url_for_dir(path)
        if hasattr(url, "__await__"):
            url = await url  # type: ignore[assignment]
        if not url:
            return False
        actual = _parse_github_repository(str(url))
        if not actual:
            return False
        return actual.lower() == expected_repo.lower()
    except OSError:
        return False


def remove_path_from_repo(repo: str, path_to_remove: str) -> None:
    repo_key = repo.lower()
    config = _get_global_config()
    paths_map = dict(config.get("githubRepoPaths") or {})
    existing = list(paths_map.get(repo_key, []))
    updated = [p for p in existing if p != path_to_remove]
    if len(updated) == len(existing):
        return
    if not updated:
        del paths_map[repo_key]
    else:
        paths_map[repo_key] = updated

    def _merge(c: dict[str, Any]) -> dict[str, Any]:
        return {**c, "githubRepoPaths": paths_map}

    _save_global_config(_merge)
    log_for_debugging(f"Removed {path_to_remove} from tracked paths for repo {repo_key}")
