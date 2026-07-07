"""Keystroke / chord parsing (port of src/keybindings/parser.ts)."""

from __future__ import annotations

from hare.keybindings.types import Chord, KeybindingBlock, ParsedBinding, ParsedKeystroke


def parse_keystroke(input: str) -> ParsedKeystroke:
    parts = input.split("+")
    ks = ParsedKeystroke(key="")
    for part in parts:
        lower = part.lower()
        match lower:
            case "ctrl" | "control":
                ks.ctrl = True
            case "alt" | "opt" | "option":
                ks.alt = True
            case "shift":
                ks.shift = True
            case "meta":
                ks.meta = True
            case "cmd" | "command" | "super" | "win":
                ks.super = True
            case "esc":
                ks.key = "escape"
            case "return":
                ks.key = "enter"
            case "space":
                ks.key = " "
            case "↑":
                ks.key = "up"
            case "↓":
                ks.key = "down"
            case "←":
                ks.key = "left"
            case "→":
                ks.key = "right"
            case _:
                ks.key = lower
    return ks


def parse_chord(input: str) -> Chord:
    if input == " ":
        return [parse_keystroke("space")]
    return [parse_keystroke(s) for s in input.strip().split()]


def _key_to_display_name(key: str) -> str:
    match key:
        case "escape":
            return "Esc"
        case " ":
            return "Space"
        case "enter":
            return "Enter"
        case "up":
            return "↑"
        case "down":
            return "↓"
        case "left":
            return "←"
        case "right":
            return "→"
        case "pageup":
            return "PageUp"
        case "pagedown":
            return "PageDown"
        case _:
            return key


def keystroke_to_string(ks: ParsedKeystroke) -> str:
    parts: list[str] = []
    if ks.ctrl:
        parts.append("ctrl")
    if ks.alt:
        parts.append("alt")
    if ks.shift:
        parts.append("shift")
    if ks.meta:
        parts.append("meta")
    if ks.super:
        parts.append("cmd")
    parts.append(_key_to_display_name(ks.key))
    return "+".join(parts)


def chord_to_string(chord: Chord) -> str:
    return " ".join(keystroke_to_string(k) for k in chord)


DisplayPlatform = str  # 'macos' | 'windows' | 'linux' | ...


def keystroke_to_display_string(
    ks: ParsedKeystroke, platform: DisplayPlatform = "linux"
) -> str:
    parts: list[str] = []
    if ks.ctrl:
        parts.append("ctrl")
    if ks.alt or ks.meta:
        parts.append("opt" if platform == "macos" else "alt")
    if ks.shift:
        parts.append("shift")
    if ks.super:
        parts.append("cmd" if platform == "macos" else "super")
    parts.append(_key_to_display_name(ks.key))
    return "+".join(parts)


def chord_to_display_string(chord: Chord, platform: DisplayPlatform = "linux") -> str:
    return " ".join(keystroke_to_display_string(k, platform) for k in chord)


def parse_bindings(blocks: list[KeybindingBlock]) -> list[ParsedBinding]:
    bindings: list[ParsedBinding] = []
    for block in blocks:
        for key, action in block.bindings.items():
            bindings.append(
                ParsedBinding(chord=parse_chord(key), action=action, context=block.context)
            )
    return bindings
