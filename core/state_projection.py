"""Safe, deterministic projections of mutable CognitiveEngine state.

The projection intentionally contains no conversation or memory content.  It is
small enough to attach to runtime events and deterministic enough to compare in
offline replay.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from contextlib import nullcontext
from typing import Any, Iterable, Mapping

from core.agent_state import AgentState


PROJECTION_SCHEMA_VERSION = 1

# These are the scalar fields currently persisted by SelfModel.save_state().
# Keeping an explicit allowlist prevents newly added text, identifiers, or
# container fields from leaking into the event journal by accident.
SAFE_EGO_SCALARS = (
    "mood",
    "stress",
    "fatigue",
    "curiosity",
    "social_need",
    "integrity",
    "is_identity_crisis",
    "energy",
    "atp_level",
    "fatigue_mild",
    "fatigue_severe",
    "fatigue_critical",
    "depression_mild",
    "depression_severe",
    "depression_critical",
    "mania_mild",
    "mania_severe",
    "stress_mild",
    "stress_severe",
    "stress_critical",
    "dopamine_receptors",
    "dopamine_level",
    "resilience",
    "sleep_debt",
)


def canonical_json(value: Any) -> str:
    """Return the canonical JSON representation used for hashes and replay."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def projection_hash(projection: Mapping[str, Any]) -> str:
    """Return a stable SHA-256 hex digest for a valid JSON projection."""

    encoded = canonical_json(projection).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _optional_lock(owner: Any, attribute: str):
    lock = getattr(owner, attribute, None)
    return lock if lock is not None else nullcontext()


def capture_state_projection(engine: Any) -> dict[str, Any]:
    """Capture a privacy-safe engine projection without nested engine locks.

    State-machine, ego, and STM reads deliberately happen in separate critical
    sections.  The snapshot is therefore observational rather than globally
    atomic, but cannot introduce the ego/STM/state lock inversion that a single
    multi-lock snapshot would risk.
    """

    state_machine = getattr(engine, "state_machine", None)
    state_value = getattr(state_machine, "state", None)
    state_name = getattr(state_value, "name", None)
    if state_name is None and isinstance(state_value, str):
        state_name = state_value

    ego_projection: dict[str, int | float | bool] = {}
    ego = getattr(engine, "ego", None)
    if ego is not None:
        with _optional_lock(ego, "lock"):
            for field in SAFE_EGO_SCALARS:
                if not hasattr(ego, field):
                    continue
                value = getattr(ego, field)
                # bool is intentionally accepted, but arbitrary Number
                # implementations (Decimal, numpy scalars) are not canonical
                # stdlib JSON values.
                if type(value) in (bool, int, float):
                    ego_projection[field] = value

    stm_count = 0
    with _optional_lock(engine, "stm_lock"):
        stm = getattr(engine, "short_term_buffer", ())
        try:
            stm_count = len(stm)
        except TypeError:
            stm_count = 0

    return {
        "schema_version": PROJECTION_SCHEMA_VERSION,
        "agent_state": state_name,
        "ego": ego_projection,
        "stm": {"count": stm_count},
    }


# Short alias for callers that already establish the state-specific context.
capture_projection = capture_state_projection


def _escape_pointer_token(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _unescape_pointer_token(token: str) -> str:
    # Reject malformed escapes instead of silently targeting the wrong key.
    index = 0
    output: list[str] = []
    while index < len(token):
        char = token[index]
        if char != "~":
            output.append(char)
            index += 1
            continue
        if index + 1 >= len(token) or token[index + 1] not in ("0", "1"):
            raise ValueError(f"invalid JSON pointer escape in {token!r}")
        output.append("~" if token[index + 1] == "0" else "/")
        index += 2
    return "".join(output)


def _child_path(parent: str, key: str) -> str:
    return f"{parent}/{_escape_pointer_token(key)}"


def _diff(before: Any, after: Any, path: str, output: list[dict[str, Any]]) -> None:
    if before == after and type(before) is type(after):
        return

    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(set(before) | set(after)):
            child_path = _child_path(path, str(key))
            if key not in after:
                output.append({"op": "remove", "path": child_path})
            elif key not in before:
                output.append(
                    {"op": "add", "path": child_path, "value": copy.deepcopy(after[key])}
                )
            else:
                _diff(before[key], after[key], child_path, output)
        return

    # Lists are intentionally replaced as a unit.  This keeps patches stable
    # when elements move and avoids exposing index-level implementation detail.
    output.append({"op": "replace", "path": path, "value": copy.deepcopy(after)})


def diff_projection(before: Any, after: Any) -> list[dict[str, Any]]:
    """Produce a deterministic JSON-patch subset from ``before`` to ``after``."""

    patch: list[dict[str, Any]] = []
    _diff(before, after, "", patch)
    return patch


def _pointer_parts(path: str) -> list[str]:
    if path == "":
        return []
    if not isinstance(path, str) or not path.startswith("/"):
        raise ValueError(f"invalid JSON pointer path: {path!r}")
    return [_unescape_pointer_token(token) for token in path[1:].split("/")]


def apply_projection_patch(projection: Any, patch: Iterable[Mapping[str, Any]]) -> Any:
    """Apply a patch returned by :func:`diff_projection` to a deep copy."""

    result = copy.deepcopy(projection)
    for operation in patch:
        op = operation.get("op")
        path = operation.get("path")
        parts = _pointer_parts(path)

        if not parts:
            if op == "remove":
                raise ValueError("the projection root cannot be removed")
            if op not in ("add", "replace") or "value" not in operation:
                raise ValueError(f"invalid root patch operation: {operation!r}")
            result = copy.deepcopy(operation["value"])
            continue

        parent = result
        for token in parts[:-1]:
            if not isinstance(parent, dict) or token not in parent:
                raise KeyError(path)
            parent = parent[token]
        if not isinstance(parent, dict):
            raise TypeError(f"patch parent is not an object: {path!r}")

        key = parts[-1]
        if op == "remove":
            if key not in parent:
                raise KeyError(path)
            del parent[key]
        elif op == "add":
            if "value" not in operation:
                raise ValueError(f"add operation has no value: {operation!r}")
            parent[key] = copy.deepcopy(operation["value"])
        elif op == "replace":
            if key not in parent:
                raise KeyError(path)
            if "value" not in operation:
                raise ValueError(f"replace operation has no value: {operation!r}")
            parent[key] = copy.deepcopy(operation["value"])
        else:
            raise ValueError(f"unsupported patch operation: {op!r}")

    return result


def _resolve_stm_limit(stm_max_entries: int | None) -> int | None:
    if stm_max_entries is not None:
        return stm_max_entries
    try:
        from config import Config

        value = getattr(Config, "STM_MAX_ENTRIES", None)
        return value if type(value) is int else None
    except (ImportError, AttributeError, TypeError, ValueError):
        return None


def validate_projection(
    projection: Any,
    stm_max_entries: int | None = None,
) -> tuple[str, ...]:
    """Return deterministic invariant violations; an empty tuple is valid."""

    violations: list[str] = []
    if not isinstance(projection, dict):
        return ("projection must be an object",)

    if projection.get("schema_version") != PROJECTION_SCHEMA_VERSION:
        violations.append(
            f"schema_version must be {PROJECTION_SCHEMA_VERSION}"
        )

    state = projection.get("agent_state")
    if not isinstance(state, str) or state not in AgentState.__members__:
        violations.append(f"agent_state is invalid: {state!r}")

    ego = projection.get("ego")
    if not isinstance(ego, dict):
        violations.append("ego must be an object")
        ego = {}

    for key in sorted(ego):
        value = ego[key]
        if type(value) in (int, float) and not math.isfinite(value):
            violations.append(f"ego.{key} must be finite")

    def bounded(key: str, lower: float, upper: float) -> None:
        if key not in ego:
            return
        value = ego[key]
        if type(value) not in (int, float) or not math.isfinite(value):
            if not (type(value) in (int, float) and not math.isfinite(value)):
                violations.append(f"ego.{key} must be numeric")
            return
        if not lower <= value <= upper:
            violations.append(f"ego.{key} must be in [{lower:g}, {upper:g}]")

    bounded("mood", -1.0, 1.0)
    for key in (
        "stress",
        "integrity",
        "curiosity",
        "social_need",
        "energy",
        "atp_level",
        "dopamine_level",
        "resilience",
    ):
        bounded(key, 0.0, 1.0)

    if "fatigue" in ego:
        fatigue = ego["fatigue"]
        if type(fatigue) not in (int, float) or not math.isfinite(fatigue):
            if not (type(fatigue) in (int, float) and not math.isfinite(fatigue)):
                violations.append("ego.fatigue must be numeric")
        elif fatigue < 0:
            violations.append("ego.fatigue must be >= 0")

    stm = projection.get("stm")
    if not isinstance(stm, dict):
        violations.append("stm must be an object")
    else:
        count = stm.get("count")
        if type(count) is not int:
            violations.append("stm.count must be an integer")
        elif count < 0:
            violations.append("stm.count must be >= 0")
        else:
            limit = _resolve_stm_limit(stm_max_entries)
            if limit is not None and count > limit:
                violations.append(f"stm.count must be <= {limit}")

    return tuple(violations)


__all__ = [
    "PROJECTION_SCHEMA_VERSION",
    "SAFE_EGO_SCALARS",
    "apply_projection_patch",
    "canonical_json",
    "capture_projection",
    "capture_state_projection",
    "diff_projection",
    "projection_hash",
    "validate_projection",
]
