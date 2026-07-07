"""Shell configuration file helpers (port of shellConfig.ts)."""

from __future__ import annotations

import os
import re
from pathlib import Path

CLAUDE_ALIAS_REGEX = re.compile(r"^\s*alias\s+claude\s*=")


def get_local_claude_path() -> str:
    """Installer default alias target — stub matching ~/.claude/local/claude."""
    return str(Path.home() / ".claude" / "local" / "claude")


def get_shell_config_paths(
    *,
    env: dict[str, str | None] | None = None,
    homedir: str | None = None,
) -> dict[str, str]:
    home = homedir or str(Path.home())
    env = env if env is not None else dict(os.environ)
    zdot = env.get("ZDOTDIR") or home
    return {
        "zsh": str(Path(zdot) / ".zshrc"),
        "bash": str(Path(home) / ".bashrc"),
        "fish": str(Path(home) / ".config" / "fish" / "config.fish"),
    }


def filter_claude_aliases(lines: list[str]) -> tuple[list[str], bool]:
    had_alias = False
    filtered: list[str] = []
    local_path = get_local_claude_path()

    for line in lines:
        if CLAUDE_ALIAS_REGEX.search(line):
            m = re.search(r'alias\s+claude\s*=\s*["\']([^"\']+)["\']', line)
            if not m:
                m = re.search(r"alias\s+claude\s*=\s*([^#\n]+)", line)
            if m:
                target = m.group(1).strip()
                if target == local_path:
                    had_alias = True
                    continue
        filtered.append(line)

    return filtered, had_alias


async def read_file_lines(file_path: str) -> list[str] | None:
    try:
        text = Path(file_path).read_text(encoding="utf-8")
        return text.split("\n")
    except OSError:
        return None


async def write_file_lines(file_path: str, lines: list[str]) -> None:
    Path(file_path).write_text("\n".join(lines), encoding="utf-8")


async def find_claude_alias(
    *,
    env: dict[str, str | None] | None = None,
    homedir: str | None = None,
) -> str | None:
    for path in get_shell_config_paths(env=env, homedir=homedir).values():
        lines = await read_file_lines(path)
        if not lines:
            continue
        for line in lines:
            if CLAUDE_ALIAS_REGEX.search(line):
                m = re.search(r'alias\s+claude=["\']?([^"\'\s]+)', line)
                if m:
                    return m.group(1)
    return None


async def find_valid_claude_alias(
    *,
    env: dict[str, str | None] | None = None,
    homedir: str | None = None,
) -> str | None:
    alias_target = await find_claude_alias(env=env, homedir=homedir)
    if not alias_target:
        return None
    home = homedir or str(Path.home())
    expanded = alias_target.replace("~", home, 1) if alias_target.startswith("~") else alias_target
    p = Path(expanded)
    try:
        if p.is_file() or p.is_symlink():
            return alias_target
    except OSError:
        pass
    return None
