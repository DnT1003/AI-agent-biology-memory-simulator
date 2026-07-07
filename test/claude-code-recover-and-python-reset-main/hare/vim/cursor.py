"""Minimal Cursor for vim motions (stub; port targets src/utils/Cursor.js)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Cursor:
    """Subset of Ink/terminal Cursor used by vim operators."""

    text: str
    offset: int = 0
    measured_text: object | None = None

    def __post_init__(self) -> None:
        if self.measured_text is None:
            self.measured_text = self

    def equals(self, other: object) -> bool:
        return isinstance(other, Cursor) and other.offset == self.offset and other.text == self.text

    def left(self) -> Cursor:
        return Cursor(self.text, max(0, self.offset - 1))

    def right(self) -> Cursor:
        return Cursor(self.text, min(len(self.text), self.offset + 1))

    def down_logical_line(self) -> Cursor:
        rest = self.text[self.offset :]
        nl = rest.find("\n")
        if nl == -1:
            return self
        return Cursor(self.text, self.offset + nl + 1)

    def up_logical_line(self) -> Cursor:
        before = self.text[: self.offset]
        if "\n" not in before:
            return Cursor(self.text, 0)
        prev_nl = before.rfind("\n", 0, len(before) - 1)
        start = 0 if prev_nl == -1 else prev_nl + 1
        return Cursor(self.text, start)

    def start_of_logical_line(self) -> Cursor:
        before = self.text[: self.offset]
        nl = before.rfind("\n")
        return Cursor(self.text, 0 if nl == -1 else nl + 1)

    def end_of_logical_line(self) -> Cursor:
        rest = self.text[self.offset :]
        nl = rest.find("\n")
        end = len(self.text) if nl == -1 else self.offset + nl
        return Cursor(self.text, end)

    def first_non_blank_in_logical_line(self) -> Cursor:
        c = self.start_of_logical_line()
        i = c.offset
        while i < len(self.text) and self.text[i] in " \t":
            i += 1
        return Cursor(self.text, min(i, len(self.text)))

    def start_of_first_line(self) -> Cursor:
        return Cursor(self.text, 0)

    def start_of_last_line(self) -> Cursor:
        if not self.text:
            return self
        if self.text[-1] == "\n":
            lines = self.text[:-1].split("\n")
        else:
            lines = self.text.split("\n")
        if not lines:
            return Cursor(self.text, 0)
        off = sum(len(x) + 1 for x in lines[:-1])
        return Cursor(self.text, off)

    def go_to_line(self, n: int) -> Cursor:
        lines = self.text.split("\n")
        idx = max(0, min(n - 1, len(lines) - 1))
        off = sum(len(lines[i]) + 1 for i in range(idx))
        return Cursor(self.text, min(off, len(self.text)))

    def is_at_end(self) -> bool:
        return self.offset >= len(self.text)

    def get_position(self) -> tuple[int, int]:
        line = self.text.count("\n", 0, self.offset)
        return (0, line)

    def find_character(self, ch: str, find_type: str, count: int) -> int | None:
        _ = count
        slice_ = self.text[self.offset + 1 :]
        idx = slice_.find(ch)
        if idx == -1:
            return None
        return self.offset + 1 + idx

    def next_offset(self, off: int) -> int:
        return min(len(self.text), off + 1)

    def snap_out_of_image_ref(self, off: int, _which: str) -> int:
        return off


def is_vim_word_char(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


def is_vim_whitespace(ch: str) -> bool:
    return ch in " \t\n\r"


def is_vim_punctuation(ch: str) -> bool:
    return not (is_vim_word_char(ch) or is_vim_whitespace(ch))
