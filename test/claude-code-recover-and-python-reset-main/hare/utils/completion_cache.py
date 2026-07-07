"""Shell completion install/regenerate (`completionCache.ts`)."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from hare.utils.debug import log_for_debugging
from hare.utils.errors import is_enoent as is_enoent_error
from hare.utils.log import log_error


@dataclass
class ShellInfo:
    name: str
    rc_file: str
    cache_file: str
    completion_line: str
    shell_flag: str


def detect_shell() -> ShellInfo | None:
    shell = os.environ.get("SHELL", "")
    home = str(Path.home())
    claude_dir = os.path.join(home, ".claude")

    if shell.endswith("/zsh") or shell.endswith("zsh.exe"):
        cache = os.path.join(claude_dir, "completion.zsh")
        return ShellInfo(
            name="zsh",
            rc_file=os.path.join(home, ".zshrc"),
            cache_file=cache,
            completion_line=f'[[ -f "{cache}" ]] && source "{cache}"',
            shell_flag="zsh",
        )
    if shell.endswith("/bash") or shell.endswith("bash.exe"):
        cache = os.path.join(claude_dir, "completion.bash")
        return ShellInfo(
            name="bash",
            rc_file=os.path.join(home, ".bashrc"),
            cache_file=cache,
            completion_line=f'[ -f "{cache}" ] && source "{cache}"',
            shell_flag="bash",
        )
    if shell.endswith("/fish") or shell.endswith("fish.exe"):
        xdg = os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
        cache = os.path.join(claude_dir, "completion.fish")
        return ShellInfo(
            name="fish",
            rc_file=os.path.join(xdg, "fish", "config.fish"),
            cache_file=cache,
            completion_line=f'[ -f "{cache}" ] && source "{cache}"',
            shell_flag="fish",
        )
    return None


def _format_path_link(file_path: str) -> str:
    return file_path


async def setup_shell_completion(theme: str) -> str:  # theme unused — color stub
    sh = detect_shell()
    if not sh:
        return ""
    os.makedirs(os.path.dirname(sh.cache_file), exist_ok=True)
    claude_bin = os.path.abspath(sys_argv1())
    r = subprocess.run(
        [claude_bin, "completion", sh.shell_flag, "--output", sh.cache_file],
        capture_output=True,
        timeout=120,
    )
    if r.returncode != 0:
        return f"\nCould not generate {sh.name} shell completions\nRun manually: claude completion {sh.shell_flag} > {sh.cache_file}\n"

    existing = ""
    try:
        existing = Path(sh.rc_file).read_text(encoding="utf-8")
        if "claude completion" in existing or sh.cache_file in existing:
            return f"\nShell completions updated for {sh.name}\nSee {_format_path_link(sh.rc_file)}\n"
    except OSError as e:
        if not is_enoent_error(e):
            log_error(e)
            return f"\nCould not install {sh.name} shell completions\nAdd to {sh.rc_file}:\n{sh.completion_line}\n"

    try:
        os.makedirs(os.path.dirname(sh.rc_file), exist_ok=True)
        sep = "\n" if existing and not existing.endswith("\n") else ""
        body = f"{existing}{sep}\n# Claude Code shell completions\n{sh.completion_line}\n"
        Path(sh.rc_file).write_text(body, encoding="utf-8")
        return f"\nInstalled {sh.name} shell completions\nAdded to {_format_path_link(sh.rc_file)}\nRun: source {sh.rc_file}\n"
    except OSError as e:
        log_error(e)
        return f"\nCould not install {sh.name} shell completions\n"


def sys_argv1() -> str:
    import sys

    return sys.argv[1] if len(sys.argv) > 1 else "claude"


async def regenerate_completion_cache() -> None:
    sh = detect_shell()
    if not sh:
        return
    log_for_debugging(f"update: Regenerating {sh.name} completion cache")
    claude_bin = sys_argv1()
    r = subprocess.run(
        [claude_bin, "completion", sh.shell_flag, "--output", sh.cache_file],
        capture_output=True,
        timeout=120,
    )
    if r.returncode != 0:
        log_for_debugging(f"update: Failed to regenerate {sh.name} completion cache")
        return
    log_for_debugging(f"update: Regenerated {sh.name} completion cache at {sh.cache_file}")
