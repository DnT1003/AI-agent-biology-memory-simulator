"""OSC 8 terminal hyperlinks — port of `hyperlink.ts`."""

from __future__ import annotations

OSC8_START = "\x1b]8;;"
OSC8_END = "\x07"


def supports_hyperlinks() -> bool:
    """Stub: real impl reads TERM/WT_SESSION, etc."""
    return False


def create_hyperlink(url: str, content: str | None = None, *, supports_hyperlinks_override: bool | None = None) -> str:
    has_support = supports_hyperlinks_override if supports_hyperlinks_override is not None else supports_hyperlinks()
    if not has_support:
        return url
    display = content if content is not None else url
    # Blue ANSI via simple escape (no chalk dependency)
    colored = f"\x1b[34m{display}\x1b[0m"
    return f"{OSC8_START}{url}{OSC8_END}{colored}{OSC8_START}{OSC8_END}"
