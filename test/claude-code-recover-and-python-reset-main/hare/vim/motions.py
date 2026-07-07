"""Vim motions (port of src/vim/motions.ts)."""

from __future__ import annotations

from hare.vim.cursor import Cursor


def resolve_motion(key: str, cursor: Cursor, count: int) -> Cursor:
    result = cursor
    for _ in range(count):
        nxt = _apply_single_motion(key, result)
        if nxt.equals(result):
            break
        result = nxt
    return result


def _apply_single_motion(key: str, cursor: Cursor) -> Cursor:
    match key:
        case "h":
            return cursor.left()
        case "l":
            return cursor.right()
        case "j":
            return cursor.down_logical_line()
        case "k":
            return cursor.up_logical_line()
        case "w":
            return cursor  # stub: nextVimWord
        case "b":
            return cursor
        case "0":
            return cursor.start_of_logical_line()
        case "^":
            return cursor.first_non_blank_in_logical_line()
        case "$":
            return cursor.end_of_logical_line()
        case "G":
            return cursor.start_of_last_line()
        case _:
            return cursor


def is_inclusive_motion(key: str) -> bool:
    return key in "eE$"


def is_linewise_motion(key: str) -> bool:
    return key in "jkG" or key == "gg"
