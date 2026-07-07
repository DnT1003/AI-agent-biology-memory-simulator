"""Shortcut display helpers (port of src/keybindings/shortcutFormat.ts)."""

from __future__ import annotations

from hare.keybindings.load_user_bindings import load_keybindings_sync
from hare.keybindings.resolver import get_binding_display_text
from hare.keybindings.types import KeybindingContextName


_LOGGED_FALLBACKS: set[str] = set()


def _log_fallback(action: str, context: KeybindingContextName, fallback: str) -> None:
    key = f"{action}:{context}"
    if key in _LOGGED_FALLBACKS:
        return
    _LOGGED_FALLBACKS.add(key)
    # Stub: wire to analytics log_event('tengu_keybinding_fallback_used', ...)
    pass


def get_shortcut_display(
    action: str,
    context: KeybindingContextName,
    fallback: str,
) -> str:
    bindings = load_keybindings_sync()
    resolved = get_binding_display_text(action, context, bindings)
    if resolved is None:
        _log_fallback(action, context, fallback)
        return fallback
    return resolved
