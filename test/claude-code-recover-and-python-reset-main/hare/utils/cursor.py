"""
Terminal input cursor, measured text, and kill ring.

Port of: src/utils/Cursor.ts — Ink `stringWidth` / `wrapAnsi` replaced with
`wcwidth`-aware stubs + `textwrap`; grapheme segmentation uses naive Unicode
clusters (extend with `regex` or `grapheme` for full parity).
"""

from __future__ import annotations

import re
import textwrap
import unicodedata
from dataclasses import dataclass
from typing import Callable, Literal

# --- Kill ring (global, matches TS module state) ---
_KILL_RING_MAX_SIZE = 10
_kill_ring: list[str] = []
_kill_ring_index = 0
_last_action_was_kill = False
_last_yank_start = 0
_last_yank_length = 0
_last_action_was_yank = False


def push_to_kill_ring(text: str, direction: Literal["prepend", "append"] = "append") -> None:
    global _last_action_was_kill, _last_action_was_yank
    if text:
        if _last_action_was_kill and _kill_ring:
            if direction == "prepend":
                _kill_ring[0] = text + _kill_ring[0]
            else:
                _kill_ring[0] = _kill_ring[0] + text
        else:
            _kill_ring.insert(0, text)
            if len(_kill_ring) > _KILL_RING_MAX_SIZE:
                _kill_ring.pop()
        _last_action_was_kill = True
        _last_action_was_yank = False


def get_last_kill() -> str:
    return _kill_ring[0] if _kill_ring else ""


def get_kill_ring_item(index: int) -> str:
    if not _kill_ring:
        return ""
    n = len(_kill_ring)
    idx = ((index % n) + n) % n
    return _kill_ring[idx]


def get_kill_ring_size() -> int:
    return len(_kill_ring)


def clear_kill_ring() -> None:
    global _kill_ring_index, _last_action_was_kill, _last_action_was_yank
    global _last_yank_start, _last_yank_length
    _kill_ring.clear()
    _kill_ring_index = 0
    _last_action_was_kill = False
    _last_action_was_yank = False
    _last_yank_start = 0
    _last_yank_length = 0


def reset_kill_accumulation() -> None:
    global _last_action_was_kill
    _last_action_was_kill = False


def record_yank(start: int, length: int) -> None:
    global _last_yank_start, _last_yank_length, _last_action_was_yank, _kill_ring_index
    _last_yank_start = start
    _last_yank_length = length
    _last_action_was_yank = True
    _kill_ring_index = 0


def can_yank_pop() -> bool:
    return _last_action_was_yank and len(_kill_ring) > 1


def yank_pop() -> dict[str, int | str] | None:
    global _kill_ring_index
    if not _last_action_was_yank or len(_kill_ring) <= 1:
        return None
    _kill_ring_index = (_kill_ring_index + 1) % len(_kill_ring)
    text = _kill_ring[_kill_ring_index]
    return {"text": text, "start": _last_yank_start, "length": _last_yank_length}


def update_yank_length(length: int) -> None:
    global _last_yank_length
    _last_yank_length = length


def reset_yank_state() -> None:
    global _last_action_was_yank
    _last_action_was_yank = False


VIM_WORD_CHAR_REGEX = re.compile(r"^[\w]$", re.UNICODE)
WHITESPACE_REGEX = re.compile(r"\s")


def is_vim_word_char(ch: str) -> bool:
    return bool(ch) and bool(VIM_WORD_CHAR_REGEX.match(ch))


def is_vim_whitespace(ch: str) -> bool:
    return bool(WHITESPACE_REGEX.match(ch))


def is_vim_punctuation(ch: str) -> bool:
    return bool(ch) and not is_vim_whitespace(ch) and not is_vim_word_char(ch)


def string_width(s: str) -> int:
    try:
        import wcwidth  # type: ignore[import-not-found]

        return wcwidth.wcswidth(s) if wcwidth.wcswidth(s) >= 0 else len(s)
    except Exception:
        return len(unicodedata.normalize("NFC", s))


def wrap_ansi(text: str, width: int, **_opts: object) -> str:
    """Stub: strip ANSI for wrapping width; real Ink wraps with ANSI awareness."""
    plain = re.sub(r"\x1b\[[0-9;]*m", "", text)
    lines = textwrap.wrap(plain, width=width) or [""]
    return "\n".join(lines)


@dataclass
class Position:
    line: int
    column: int


@dataclass
class WrappedLine:
    text: str
    start_offset: int
    is_preceded_by_newline: bool
    ends_with_newline: bool = False


class MeasuredText:
    def __init__(self, text: str, columns: int) -> None:
        self.text = unicodedata.normalize("NFC", text)
        self.columns = columns
        self._wrapped_lines: list[WrappedLine] | None = None
        self._grapheme_boundaries: list[int] | None = None

    def _grapheme_boundaries_list(self) -> list[int]:
        if self._grapheme_boundaries is None:
            # Stub: code-point boundaries (Python str indices); full TS uses grapheme clusters.
            self._grapheme_boundaries = list(range(len(self.text) + 1))
        return self._grapheme_boundaries

    def _ensure_wrapped(self) -> list[WrappedLine]:
        if self._wrapped_lines is None:
            wrapped = wrap_ansi(self.text, self.columns, hard=True, trim=False)
            lines = wrapped.split("\n")
            out: list[WrappedLine] = []
            off = 0
            for i, line in enumerate(lines):
                start = self.text.find(line, off) if line else off
                if start == -1:
                    start = off
                out.append(
                    WrappedLine(
                        text=line,
                        start_offset=start,
                        is_preceded_by_newline=i == 0 or self.text[start - 1] == "\n",
                    )
                )
                off = start + len(line)
            self._wrapped_lines = out or [WrappedLine("", 0, True)]
        return self._wrapped_lines

    def get_wrapped_text(self) -> list[str]:
        return [ln.text if ln.is_preceded_by_newline else ln.text.lstrip() for ln in self._ensure_wrapped()]

    def get_wrapped_lines(self) -> list[WrappedLine]:
        return self._ensure_wrapped()

    def get_line_length(self, line: int) -> int:
        w = self._ensure_wrapped()
        if line < 0 or line >= len(w):
            return 0
        return string_width(w[line].text)

    def get_word_boundaries(self) -> list[dict[str, int | bool]]:
        """Intl.Segmenter substitute — word-like spans (simplified)."""
        out: list[dict[str, int | bool]] = []
        for m in re.finditer(r"\w+", self.text):
            out.append({"start": m.start(), "end": m.end(), "isWordLike": True})
        return out

    def next_offset(self, offset: int) -> int:
        b = self._grapheme_boundaries_list()
        for i, x in enumerate(b):
            if x > offset:
                return x
        return len(self.text)

    def prev_offset(self, offset: int) -> int:
        b = self._grapheme_boundaries_list()
        prev = 0
        for x in b:
            if x >= offset:
                break
            prev = x
        return prev

    def snap_to_grapheme_boundary(self, offset: int) -> int:
        if offset <= 0:
            return 0
        if offset >= len(self.text):
            return len(self.text)
        b = self._grapheme_boundaries_list()
        lo, hi = 0, len(b) - 1
        while lo < hi:
            mid = (lo + hi + 1) >> 1
            if b[mid] <= offset:
                lo = mid
            else:
                hi = mid - 1
        return b[lo]

    def get_offset_from_position(self, position: Position) -> int:
        lines = self._ensure_wrapped()
        if position.line < 0 or position.line >= len(lines):
            return len(self.text)
        wl = lines[position.line]
        idx = wl.start_offset + min(len(wl.text), position.column)
        return min(idx, len(self.text))

    def get_position_from_offset(self, offset: int) -> Position:
        lines = self._ensure_wrapped()
        for li, wl in enumerate(lines):
            end = wl.start_offset + len(wl.text)
            if offset <= end:
                col = string_width(self.text[wl.start_offset : offset])
                return Position(line=li, column=max(0, col))
        last = lines[-1]
        return Position(line=len(lines) - 1, column=string_width(last.text))

    @property
    def line_count(self) -> int:
        return len(self._ensure_wrapped())


class Cursor:
    def __init__(
        self,
        measured_text: MeasuredText,
        offset: int = 0,
        selection: int = 0,
    ) -> None:
        del selection
        self.measured_text = measured_text
        self.offset = max(0, min(len(measured_text.text), offset))

    @staticmethod
    def from_text(text: str, columns: int, offset: int = 0, selection: int = 0) -> Cursor:
        return Cursor(MeasuredText(text, columns - 1), offset, selection)

    @property
    def text(self) -> str:
        return self.measured_text.text

    def get_position(self) -> Position:
        return self.measured_text.get_position_from_offset(self.offset)

    def left(self) -> Cursor:
        if self.offset == 0:
            return self
        chip = self.image_ref_ending_at(self.offset)
        if chip:
            return Cursor(self.measured_text, chip["start"])
        prev = self.measured_text.prev_offset(self.offset)
        return Cursor(self.measured_text, prev)

    def right(self) -> Cursor:
        if self.offset >= len(self.text):
            return self
        chip = self.image_ref_starting_at(self.offset)
        if chip:
            return Cursor(self.measured_text, chip["end"])
        nxt = self.measured_text.next_offset(self.offset)
        return Cursor(self.measured_text, min(nxt, len(self.text)))

    def image_ref_ending_at(self, offset: int) -> dict[str, int] | None:
        m = re.search(r"\[Image #\d+\]$", self.text[:offset])
        if not m:
            return None
        start = offset - len(m.group(0))
        return {"start": start, "end": offset}

    def image_ref_starting_at(self, offset: int) -> dict[str, int] | None:
        m = re.match(r"^\[Image #\d+\]", self.text[offset:])
        if not m:
            return None
        return {"start": offset, "end": offset + len(m.group(0))}

    def is_at_end(self) -> bool:
        return self.offset >= len(self.text)

    def is_at_start(self) -> bool:
        return self.offset == 0

    def insert(self, s: str) -> Cursor:
        t = self.text[: self.offset] + unicodedata.normalize("NFC", s) + self.text[self.offset :]
        return Cursor.from_text(t, self.measured_text.columns + 1, self.offset + len(s))

    def render(
        self,
        cursor_char: str,
        mask: str,
        invert: Callable[[str], str],
        ghost_text: dict[str, Callable[[str], str] | str] | None = None,
        max_visible_lines: int | None = None,
    ) -> str:
        _ = mask, invert, ghost_text, max_visible_lines
        return self.text
