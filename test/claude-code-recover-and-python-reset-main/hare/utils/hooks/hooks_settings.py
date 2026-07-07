"""
Hook listing and display helpers.

Port of: src/utils/hooks/hooksSettings.ts
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Protocol, TypeAlias

DEFAULT_HOOK_SHELL = "bash"

HookSource: TypeAlias = Literal[
    "userSettings",
    "projectSettings",
    "localSettings",
    "policySettings",
    "pluginHook",
    "sessionHook",
    "builtinHook",
]


class _AppState(Protocol):
    """Stub application state bag."""

    pass


def is_hook_equal(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if a.get("type") != b.get("type"):
        return False
    same_if = (a.get("if") or "") == (b.get("if") or "")
    t = a.get("type")
    if t == "command":
        return (
            b.get("type") == "command"
            and a.get("command") == b.get("command")
            and (a.get("shell") or DEFAULT_HOOK_SHELL) == (b.get("shell") or DEFAULT_HOOK_SHELL)
            and same_if
        )
    if t == "prompt":
        return b.get("type") == "prompt" and a.get("prompt") == b.get("prompt") and same_if
    if t == "agent":
        return b.get("type") == "agent" and a.get("prompt") == b.get("prompt") and same_if
    if t == "http":
        return b.get("type") == "http" and a.get("url") == b.get("url") and same_if
    if t == "function":
        return False
    return False


def get_hook_display_text(hook: dict[str, Any]) -> str:
    if hook.get("statusMessage"):
        return str(hook["statusMessage"])
    t = hook.get("type")
    if t == "command":
        return str(hook.get("command", ""))
    if t in ("prompt", "agent"):
        return str(hook.get("prompt", ""))
    if t == "http":
        return str(hook.get("url", ""))
    if t == "callback":
        return "callback"
    if t == "function":
        return "function"
    return ""


def get_all_hooks(app_state: Any, settings_getter: Any | None = None) -> list[dict[str, Any]]:
    """
    Collect hooks from settings (stub: returns session hooks only unless wired).

    *settings_getter* may provide ``get_settings_for_source`` / paths.
    """
    del app_state
    hooks: list[dict[str, Any]] = []
    if settings_getter is None:
        return hooks
    return hooks


def get_hooks_for_event(app_state: Any, event: str) -> list[dict[str, Any]]:
    return [h for h in get_all_hooks(app_state) if h.get("event") == event]


def hook_source_description_display_string(source: HookSource) -> str:
    mapping: dict[str, str] = {
        "userSettings": "User settings (~/.claude/settings.json)",
        "projectSettings": "Project settings (.claude/settings.json)",
        "localSettings": "Local settings (.claude/settings.local.json)",
        "pluginHook": "Plugin hooks (~/.claude/plugins/*/hooks/hooks.json)",
        "sessionHook": "Session hooks (in-memory, temporary)",
        "builtinHook": "Built-in hooks (registered internally by Claude Code)",
    }
    return mapping.get(source, str(source))


def hook_source_header_display_string(source: HookSource) -> str:
    mapping: dict[str, str] = {
        "userSettings": "User Settings",
        "projectSettings": "Project Settings",
        "localSettings": "Local Settings",
        "pluginHook": "Plugin Hooks",
        "sessionHook": "Session Hooks",
        "builtinHook": "Built-in Hooks",
    }
    return mapping.get(source, str(source))


def hook_source_inline_display_string(source: HookSource) -> str:
    mapping: dict[str, str] = {
        "userSettings": "User",
        "projectSettings": "Project",
        "localSettings": "Local",
        "pluginHook": "Plugin",
        "sessionHook": "Session",
        "builtinHook": "Built-in",
    }
    return mapping.get(source, str(source))


def sort_matchers_by_priority(
    matchers: list[str],
    hooks_by_event_and_matcher: dict[str, dict[str, list[dict[str, Any]]]],
    selected_event: str,
) -> list[str]:
    sources_order = ["userSettings", "projectSettings", "localSettings"]

    def source_priority(src: str) -> int:
        if src in ("pluginHook", "builtinHook"):
            return 999
        try:
            return sources_order.index(src)
        except ValueError:
            return 500

    def highest_priority(match: str) -> int:
        hooks = hooks_by_event_and_matcher.get(selected_event, {}).get(match, [])
        srcs = {h.get("source") for h in hooks if h.get("source")}
        if not srcs:
            return 999
        return min(source_priority(str(s)) for s in srcs)

    return sorted(matchers, key=lambda m: (highest_priority(m), m))


def resolve_path_for_dedup(file_path: str | None) -> str | None:
    if not file_path:
        return None
    return str(Path(file_path).resolve())
