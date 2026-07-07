"""
Launch the user's external editor for a file.

Port of: src/utils/editor.ts
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

from hare.utils.debug import log_for_debugging
from hare.utils.which import which_sync

GUI_EDITORS = [
    "code",
    "cursor",
    "windsurf",
    "codium",
    "subl",
    "atom",
    "gedit",
    "notepad++",
    "notepad",
]
PLUS_N_EDITORS = re.compile(r"\b(vi|vim|nvim|nano|emacs|pico|micro|helix|hx)\b")
VSCODE_FAMILY = frozenset({"code", "cursor", "windsurf", "codium"})


def classify_gui_editor(editor: str) -> str | None:
    base = Path(editor.split(" ")[0] or "").name
    for g in GUI_EDITORS:
        if g in base:
            return g
    return None


def _gui_goto_argv(gui_family: str, file_path: str, line: int | None) -> list[str]:
    if not line:
        return [file_path]
    if gui_family in VSCODE_FAMILY:
        return ["-g", f"{file_path}:{line}"]
    if gui_family == "subl":
        return [f"{file_path}:{line}"]
    return [file_path]


class _InkStub:
    """Placeholder for Ink alternate-screen handoff (no TUI in Python port)."""

    def enter_alternate_screen(self) -> None:
        pass

    def exit_alternate_screen(self) -> None:
        pass


def _get_ink_instance(_stdout) -> _InkStub | None:
    # TS: instances.get(process.stdout); stub always available for terminal path
    return _InkStub()


def open_file_in_external_editor(file_path: str, line: int | None = None) -> bool:
    editor = get_external_editor()
    if not editor:
        return False
    parts = editor.split(" ")
    base = parts[0] or editor
    editor_args = parts[1:]
    gui_family = classify_gui_editor(editor)

    if gui_family:
        goto_argv = _gui_goto_argv(gui_family, file_path, line)
        detached: dict = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "stdin": subprocess.DEVNULL}
        try:
            if sys.platform == "win32":
                goto_str = " ".join(f'"{a}"' for a in goto_argv)
                subprocess.Popen(
                    f"{editor} {goto_str}",
                    shell=True,
                    creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
                    **detached,
                )
            else:
                subprocess.Popen([base, *editor_args, *goto_argv], start_new_session=True, **detached)
        except OSError as e:
            log_for_debugging(f"editor spawn failed: {e}", level="error")
        return True

    ink = _get_ink_instance(sys.stdout)
    if not ink:
        return False
    use_goto_line = bool(line and PLUS_N_EDITORS.search(Path(base).name))
    ink.enter_alternate_screen()
    try:
        if sys.platform == "win32":
            line_arg = f"+{line} " if use_goto_line else ""
            cmd = f'{editor} {line_arg}"{file_path}"'
            r = subprocess.run(cmd, shell=True, stdin=sys.stdin, capture_output=False)
        else:
            args = [*editor_args]
            if use_goto_line:
                args.extend([f"+{line}", file_path])
            else:
                args.append(file_path)
            r = subprocess.run([base, *args], stdin=sys.stdin, capture_output=False)
        if r.returncode != 0:
            log_for_debugging(f"editor spawn failed: exit {r.returncode}", level="error")
            return False
        return True
    finally:
        ink.exit_alternate_screen()


@lru_cache(maxsize=1)
def get_external_editor() -> str | None:
    v = os.environ.get("VISUAL", "").strip()
    if v:
        return v
    e = os.environ.get("EDITOR", "").strip()
    if e:
        return e
    if sys.platform == "win32":
        return "start /wait notepad"
    for command in ("code", "vi", "nano"):
        if which_sync(command):
            return command
    return None
