"""
Load user keybindings from ~/.claude/keybindings.json
(port of src/keybindings/loadUserBindings.ts).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from hare.keybindings.parser import parse_bindings
from hare.keybindings.types import KeybindingBlock, ParsedBinding
from hare.keybindings.validate import KeybindingWarning, check_duplicate_keys_in_json, validate_bindings


def _claude_config_home() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR", os.path.expanduser("~/.claude")))


def get_keybindings_path() -> str:
    return str(_claude_config_home() / "keybindings.json")


def is_keybinding_customization_enabled() -> bool:
    """Stub: wire to feature flags / GrowthBook when available."""
    return os.environ.get("CLAUDE_CODE_KEYBINDING_CUSTOMIZATION", "").lower() in (
        "1",
        "true",
        "yes",
    )


def _default_parsed() -> list[ParsedBinding]:
    from hare.keybindings.default_bindings import DEFAULT_BINDINGS

    return parse_bindings(DEFAULT_BINDINGS)


@dataclass
class KeybindingsLoadResult:
    bindings: list[ParsedBinding]
    warnings: list[KeybindingWarning]


_cached_bindings: list[ParsedBinding] | None = None
_cached_warnings: list[KeybindingWarning] = []


def _parse_file(content: str) -> tuple[list[KeybindingBlock] | None, list[KeybindingWarning]]:
    warnings: list[KeybindingWarning] = []
    try:
        parsed: Any = json.loads(content)
    except json.JSONDecodeError as e:
        return None, [
            KeybindingWarning(
                type="parse_error",
                severity="error",
                message=f"Invalid JSON: {e}",
            )
        ]
    if not isinstance(parsed, dict) or "bindings" not in parsed:
        return None, [
            KeybindingWarning(
                type="parse_error",
                severity="error",
                message='keybindings.json must have a "bindings" array',
                suggestion='Use format: { "bindings": [ ... ] }',
            )
        ]
    ub = parsed["bindings"]
    if not isinstance(ub, list):
        return None, [
            KeybindingWarning(
                type="parse_error",
                severity="error",
                message='"bindings" must be an array',
            )
        ]
    blocks: list[KeybindingBlock] = []
    for item in ub:
        if not isinstance(item, dict):
            continue
        ctx = item.get("context")
        bd = item.get("bindings")
        if isinstance(ctx, str) and isinstance(bd, dict):
            blocks.append(
                KeybindingBlock(
                    context=ctx,  # type: ignore[arg-type]
                    bindings={str(k): v if v is None or isinstance(v, str) else str(v) for k, v in bd.items()},
                )
            )
    warnings.extend(check_duplicate_keys_in_json(content))
    merged_for_validation = [*_default_parsed(), *parse_bindings(blocks)]
    warnings.extend(validate_bindings(ub, merged_for_validation))
    return blocks, warnings


async def load_keybindings() -> KeybindingsLoadResult:
    default_bindings = _default_parsed()
    if not is_keybinding_customization_enabled():
        return KeybindingsLoadResult(bindings=default_bindings, warnings=[])

    path = get_keybindings_path()
    if not os.path.isfile(path):
        return KeybindingsLoadResult(bindings=default_bindings, warnings=[])

    try:
        content = Path(path).read_text(encoding="utf-8")
    except OSError as e:
        return KeybindingsLoadResult(
            bindings=default_bindings,
            warnings=[
                KeybindingWarning(
                    type="parse_error",
                    severity="error",
                    message=f"Failed to read keybindings: {e}",
                )
            ],
        )

    blocks, warns = _parse_file(content)
    if blocks is None:
        return KeybindingsLoadResult(bindings=default_bindings, warnings=warns)

    user_parsed = parse_bindings(blocks)
    merged = [*default_bindings, *user_parsed]
    return KeybindingsLoadResult(bindings=merged, warnings=warns)


def load_keybindings_sync() -> list[ParsedBinding]:
    global _cached_bindings, _cached_warnings
    if _cached_bindings is not None:
        return _cached_bindings
    res = load_keybindings_sync_with_warnings()
    _cached_bindings = res.bindings
    _cached_warnings = res.warnings
    return res.bindings


def load_keybindings_sync_with_warnings() -> KeybindingsLoadResult:
    global _cached_bindings, _cached_warnings
    if _cached_bindings is not None:
        return KeybindingsLoadResult(bindings=_cached_bindings, warnings=list(_cached_warnings))

    default_bindings = _default_parsed()
    if not is_keybinding_customization_enabled():
        _cached_bindings = default_bindings
        _cached_warnings = []
        return KeybindingsLoadResult(bindings=_cached_bindings, warnings=_cached_warnings)

    path = get_keybindings_path()
    if not os.path.isfile(path):
        _cached_bindings = default_bindings
        _cached_warnings = []
        return KeybindingsLoadResult(bindings=_cached_bindings, warnings=_cached_warnings)

    try:
        content = Path(path).read_text(encoding="utf-8")
    except OSError as e:
        _cached_bindings = default_bindings
        _cached_warnings = [
            KeybindingWarning(
                type="parse_error",
                severity="error",
                message=f"Failed to read keybindings: {e}",
            )
        ]
        return KeybindingsLoadResult(bindings=_cached_bindings, warnings=_cached_warnings)

    blocks, warns = _parse_file(content)
    if blocks is None:
        _cached_bindings = default_bindings
        _cached_warnings = warns
        return KeybindingsLoadResult(bindings=_cached_bindings, warnings=_cached_warnings)

    user_parsed = parse_bindings(blocks)
    merged = [*default_bindings, *user_parsed]
    _cached_bindings = merged
    _cached_warnings = warns
    return KeybindingsLoadResult(bindings=merged, warnings=warns)


def get_cached_keybinding_warnings() -> list[KeybindingWarning]:
    return list(_cached_warnings)


def reset_keybinding_loader_for_testing() -> None:
    global _cached_bindings, _cached_warnings
    _cached_bindings = None
    _cached_warnings = []


async def initialize_keybinding_watcher() -> None:
    """Stub: chokidar/file watcher not ported; no-op."""
    return


def dispose_keybinding_watcher() -> None:
    return


SubscribeHandler = Callable[[KeybindingsLoadResult], None]


def subscribe_to_keybinding_changes(_handler: SubscribeHandler) -> Callable[[], None]:
    return lambda: None
