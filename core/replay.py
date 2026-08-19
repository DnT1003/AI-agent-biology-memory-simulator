"""Offline replay and deterministic evaluation for Aura event journals.

This module deliberately works with immutable mapping-shaped event envelopes.  It
does not construct a :class:`CognitiveEngine`, contact a model, or execute a
tool.  Journal and state-projection helpers are imported lazily so this reader
can also be used by recovery tooling when the rest of the runtime is unavailable.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import hmac
import inspect
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence


_GLOBAL_CORRELATION = "__global__"
_INTERACTION_PREFIX = "interaction."
_TERMINAL_KINDS = {
    "interaction.finished": "terminal",
    "interaction.succeeded": "succeeded",
    "interaction.completed": "succeeded",
    "interaction.failed": "failed",
    "interaction.cancelled": "cancelled",
    "interaction.canceled": "cancelled",
    "interaction.rejected": "rejected",
    "interaction.terminal": "terminal",
}

__all__ = [
    "ReplayError",
    "ReplayReport",
    "ReplayViolation",
    "ScenarioEvaluation",
    "evaluate_scenario",
    "main",
    "replay_events",
]


class ReplayError(Exception):
    """Raised when replay input cannot be opened or interpreted at all."""


@dataclass(frozen=True, slots=True)
class ReplayViolation:
    """A deterministic integrity or scenario violation found during replay."""

    code: str
    message: str
    sequence: int | None = None
    correlation_id: str | None = None
    event_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "sequence": self.sequence,
            "correlation_id": self.correlation_id,
            "event_type": self.event_type,
        }


@dataclass(frozen=True, slots=True)
class ReplayReport:
    """Result of projecting a finite sequence of journal envelopes."""

    valid: bool
    events_seen: int
    events_replayed: int
    first_sequence: int | None
    last_sequence: int | None
    event_kinds: tuple[str, ...]
    outcomes: Mapping[str, str]
    final_projections: Mapping[str, Mapping[str, Any]]
    final_hashes: Mapping[str, str]
    violations: tuple[ReplayViolation, ...]
    selected_correlation_id: str | None = None
    selected_trace_id: str | None = None
    runs_replayed: int = 1

    @property
    def final_hash(self) -> str | None:
        """Return the only/selected final projection hash, if unambiguous."""

        if self.selected_correlation_id is not None:
            return self.final_hashes.get(self.selected_correlation_id)
        if self.selected_trace_id is not None and self.selected_trace_id in self.final_hashes:
            return self.final_hashes[self.selected_trace_id]
        if len(self.final_hashes) == 1:
            return next(iter(self.final_hashes.values()))
        return None

    @property
    def final_projection(self) -> Mapping[str, Any] | None:
        """Return the only/selected final projection, if unambiguous."""

        if self.selected_correlation_id is not None:
            return self.final_projections.get(self.selected_correlation_id)
        if (
            self.selected_trace_id is not None
            and self.selected_trace_id in self.final_projections
        ):
            return self.final_projections[self.selected_trace_id]
        if len(self.final_projections) == 1:
            return next(iter(self.final_projections.values()))
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "events_seen": self.events_seen,
            "events_replayed": self.events_replayed,
            "first_sequence": self.first_sequence,
            "last_sequence": self.last_sequence,
            "event_kinds": list(self.event_kinds),
            "outcomes": dict(self.outcomes),
            "final_projections": {
                key: copy.deepcopy(dict(value))
                for key, value in self.final_projections.items()
            },
            "final_hashes": dict(self.final_hashes),
            "violations": [violation.to_dict() for violation in self.violations],
            "selected_correlation_id": self.selected_correlation_id,
            "selected_trace_id": self.selected_trace_id,
            "runs_replayed": self.runs_replayed,
        }


@dataclass(frozen=True, slots=True)
class ScenarioEvaluation:
    """Comparison of a replay report with a deterministic expectation file."""

    passed: bool
    violations: tuple[ReplayViolation, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "violations": [violation.to_dict() for violation in self.violations],
        }


@dataclass(slots=True)
class _Lifecycle:
    accepted: int = 0
    started: int = 0
    terminal: int = 0
    terminal_outcome: str | None = None
    terminal_sequence: int | None = None


@dataclass(slots=True)
class _CallLifecycle:
    started: int = 0
    finished: int = 0
    started_sequence: int | None = None
    finished_sequence: int | None = None


@dataclass(slots=True)
class _DeliveryLifecycle:
    durable: int = 0
    acked: int = 0


def _json_default(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=_json_default,
    ).encode("utf-8")


def _canonical_event_hash(event: Mapping[str, Any]) -> str:
    envelope = {key: value for key, value in event.items() if key != "event_hash"}
    return hashlib.sha256(_canonical_json(envelope)).hexdigest()


def _fallback_projection_hash(projection: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(projection)).hexdigest()


def _event_hash(
    event: Mapping[str, Any], auth_key: bytes | None = None
) -> str:
    """Compute the declared canonical envelope hash.

    HMAC is deliberately explicit here: a caller cannot turn an unverifiable
    SHA-256 envelope into a trusted record merely by changing
    ``hash_algorithm`` to ``hmac-sha256``.
    """

    serialized = _canonical_json(
        {key: value for key, value in event.items() if key != "event_hash"}
    )
    if event.get("hash_algorithm") == "hmac-sha256":
        if auth_key is None:
            raise ReplayError("HMAC event requires an authentication key")
        return hmac.new(auth_key, serialized, hashlib.sha256).hexdigest()
    return hashlib.sha256(serialized).hexdigest()


def _projection_hash(projection: Mapping[str, Any]) -> str:
    try:
        from core import state_projection as projection_module
    except ImportError:
        return _fallback_projection_hash(projection)

    for name in (
        "projection_hash",
        "hash_projection",
        "compute_projection_hash",
        "state_hash",
    ):
        helper = getattr(projection_module, name, None)
        if callable(helper):
            return str(helper(projection))
    return _fallback_projection_hash(projection)


def _projection_invariants(projection: Mapping[str, Any]) -> tuple[str, ...]:
    """Run the shared safe-state validator when the projection module provides it."""

    try:
        from core import state_projection as projection_module
    except ImportError:
        return ()
    validator = getattr(projection_module, "validate_projection", None)
    if not callable(validator):
        return ()
    result = validator(projection)
    if result is None:
        return ()
    return tuple(str(item) for item in result)


def _merge_patch(document: Any, patch: Any) -> Any:
    """Apply RFC 7396-style merge semantics without mutating either argument."""

    if not isinstance(patch, Mapping):
        return copy.deepcopy(patch)
    result: dict[str, Any]
    if isinstance(document, Mapping):
        result = copy.deepcopy(dict(document))
    else:
        result = {}
    for key, value in patch.items():
        if value is None:
            result.pop(str(key), None)
        else:
            result[str(key)] = _merge_patch(result.get(str(key)), value)
    return result


def _json_pointer_parts(pointer: str) -> list[str]:
    if pointer == "":
        return []
    if not pointer.startswith("/"):
        raise ValueError(f"invalid JSON pointer: {pointer!r}")
    return [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]


def _apply_json_patch(document: Mapping[str, Any], operations: Sequence[Any]) -> Mapping[str, Any]:
    result: Any = copy.deepcopy(dict(document))
    for operation in operations:
        if not isinstance(operation, Mapping):
            raise ValueError("JSON patch operations must be objects")
        op = str(operation.get("op", ""))
        parts = _json_pointer_parts(str(operation.get("path", "")))
        if not parts:
            if op in {"add", "replace"}:
                result = copy.deepcopy(operation.get("value"))
                continue
            if op == "remove":
                result = {}
                continue
            raise ValueError(f"unsupported JSON patch operation: {op!r}")
        parent = result
        for part in parts[:-1]:
            if not isinstance(parent, dict) or part not in parent:
                raise ValueError(f"JSON patch path does not exist: {operation.get('path')!r}")
            parent = parent[part]
        if not isinstance(parent, dict):
            raise ValueError("only object-valued state projections can be patched")
        leaf = parts[-1]
        if op in {"add", "replace"}:
            if op == "replace" and leaf not in parent:
                raise ValueError(f"JSON patch replace path does not exist: {operation.get('path')!r}")
            parent[leaf] = copy.deepcopy(operation.get("value"))
        elif op == "remove":
            if leaf not in parent:
                raise ValueError(f"JSON patch remove path does not exist: {operation.get('path')!r}")
            del parent[leaf]
        else:
            raise ValueError(f"unsupported JSON patch operation: {op!r}")
    if not isinstance(result, Mapping):
        raise ValueError("state projection patch produced a non-object value")
    return result


def _apply_projection_patch(
    projection: Mapping[str, Any], patch: Mapping[str, Any] | Sequence[Any]
) -> Mapping[str, Any]:
    try:
        from core import state_projection as projection_module
    except ImportError:
        projection_module = None

    # The shared M1 projector uses an ordered JSON-patch array.  Mapping-shaped
    # patches remain accepted as merge patches for older/pre-verified fixtures.
    if projection_module is not None and not isinstance(patch, Mapping):
        for name in ("apply_projection_patch", "apply_patch", "patch_projection"):
            helper = getattr(projection_module, name, None)
            if callable(helper):
                result = helper(copy.deepcopy(dict(projection)), copy.deepcopy(patch))
                if not isinstance(result, Mapping):
                    raise ValueError("state projection helper returned a non-object value")
                return copy.deepcopy(dict(result))

    if isinstance(patch, Sequence) and not isinstance(patch, (str, bytes, bytearray)):
        return _apply_json_patch(projection, patch)
    if not isinstance(patch, Mapping):
        raise ValueError("state delta patch must be an object or JSON-patch array")
    return _merge_patch(projection, patch)


def _as_mapping(event: Any, ordinal: int) -> Mapping[str, Any]:
    if isinstance(event, Mapping):
        return event
    converter = getattr(event, "as_dict", None)
    if callable(converter):
        converted = converter()
        if isinstance(converted, Mapping):
            return converted
    raise ReplayError(f"event #{ordinal} is not a mapping")


def _sequence(event: Mapping[str, Any]) -> int | None:
    value = event.get("sequence")
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("sequence must be an integer")
    return value


def _kind(event: Mapping[str, Any]) -> str:
    value = event.get("event_type", event.get("kind", ""))
    return str(value)


def _correlation(event: Mapping[str, Any]) -> str:
    value = event.get("correlation_id") or event.get("trace_id") or event.get("request_id")
    return str(value) if value is not None else _GLOBAL_CORRELATION


def _matches(
    event: Mapping[str, Any], correlation_id: str | None, trace_id: str | None
) -> bool:
    if correlation_id is not None and str(event.get("correlation_id")) != correlation_id:
        return False
    if trace_id is not None and str(event.get("trace_id")) != trace_id:
        return False
    return True


def _outcome(event: Mapping[str, Any], kind: str) -> str:
    explicit = event.get("outcome")
    if explicit is None and isinstance(event.get("payload"), Mapping):
        explicit = event["payload"].get("outcome")
    if explicit is not None:
        return str(explicit)
    return _TERMINAL_KINDS.get(kind, kind.rsplit(".", 1)[-1])


def _explicit_outcome(event: Mapping[str, Any]) -> str | None:
    value = event.get("outcome")
    if value is None and isinstance(event.get("payload"), Mapping):
        value = event["payload"].get("outcome")
    return None if value is None else str(value)


def _normalize_auth_key(value: Any) -> bytes | None:
    if isinstance(value, str):
        return value.encode("utf-8")
    if value is None or isinstance(value, bytes):
        return value
    raise ReplayError("event journal authentication key must be bytes or text")


def _configured_auth_key() -> bytes | None:
    try:
        from config import Config as config_type
    except ImportError:
        return None
    value = getattr(config_type, "EVENT_JOURNAL_HMAC_KEY", None)
    if value is None:
        value = getattr(config_type, "EVENT_JOURNAL_AUTH_KEY", None)
    return _normalize_auth_key(value)


def _call_id(
    event: Mapping[str, Any],
    *,
    sequence: int | None,
    correlation: str,
    kind: str,
    family: str,
    violations: list[ReplayViolation],
) -> str | None:
    payload = event.get("payload")
    if (
        event.get("privacy") == "private_ephemeral"
        and (payload is None or payload == {})
    ):
        # The persistence boundary intentionally erased this identifier.
        return None
    value = payload.get("call_id") if isinstance(payload, Mapping) else None
    if not isinstance(value, str) or not value:
        violations.append(
            ReplayViolation(
                f"{family}.call_id_missing",
                f"{kind} requires a non-empty payload.call_id",
                sequence,
                correlation,
                kind,
            )
        )
        return None
    return value


def _is_redacted_private_call(event: Mapping[str, Any]) -> bool:
    payload = event.get("payload")
    return bool(
        event.get("privacy") == "private_ephemeral"
        and (payload is None or payload == {})
    )


def _record_redacted_call_event(
    stacks: dict[tuple[str, str], list[int | None]],
    *,
    stage: str,
    family: str,
    sequence: int | None,
    correlation: str,
    kind: str,
    violations: list[ReplayViolation],
) -> None:
    """Pair erased private calls by order without restoring a persisted ID."""

    key = (family, correlation)
    stack = stacks.setdefault(key, [])
    if stage == "started":
        stack.append(sequence)
        return
    if not stack:
        violations.append(
            ReplayViolation(
                f"{family}.finished_without_started",
                "redacted private call finished without a preceding start",
                sequence,
                correlation,
                kind,
            )
        )
        return
    # Same-family nesting is paired LIFO. This preserves privacy while still
    # proving every visible start has exactly one visible terminal event.
    stack.pop()


def _record_call_event(
    lifecycles: dict[str, _CallLifecycle],
    call_id: str,
    *,
    stage: str,
    family: str,
    sequence: int | None,
    correlation: str,
    kind: str,
    violations: list[ReplayViolation],
) -> None:
    lifecycle = lifecycles.setdefault(call_id, _CallLifecycle())
    if stage == "started":
        if lifecycle.started or lifecycle.finished:
            violations.append(
                ReplayViolation(
                    f"{family}.started_duplicate",
                    f"call {call_id!r} has more than one start or started after finish",
                    sequence,
                    correlation,
                    kind,
                )
            )
        lifecycle.started += 1
        lifecycle.started_sequence = sequence
        return
    if lifecycle.started != 1:
        violations.append(
            ReplayViolation(
                f"{family}.finished_without_started",
                f"call {call_id!r} finished without exactly one preceding start",
                sequence,
                correlation,
                kind,
            )
        )
    if lifecycle.finished:
        violations.append(
            ReplayViolation(
                f"{family}.finished_duplicate",
                f"call {call_id!r} has more than one finish",
                sequence,
                correlation,
                kind,
            )
        )
    lifecycle.finished += 1
    lifecycle.finished_sequence = sequence


def _delivery_key(event: Mapping[str, Any]) -> tuple[str, str] | None:
    payload = event.get("payload")
    if not isinstance(payload, Mapping):
        return None
    transport = payload.get("transport")
    message_id = payload.get("message_id")
    if not isinstance(transport, str) or not transport:
        return None
    if not isinstance(message_id, str) or not message_id:
        return None
    return transport, message_id


def _delivery_violations(
    events: Iterable[Mapping[str, Any]],
    *,
    correlation_id: str | None = None,
    trace_id: str | None = None,
    allow_prior_durable: bool = False,
) -> tuple[ReplayViolation, ...]:
    """Reconcile delivery ACKs without treating an in-flight durable as corrupt."""

    violations: list[ReplayViolation] = []
    lifecycles: dict[tuple[str, str], _DeliveryLifecycle] = {}
    for event in events:
        kind = _kind(event)
        if kind not in {"delivery.durable", "delivery.acked"}:
            continue
        if not _matches(event, correlation_id, trace_id):
            continue
        key = _delivery_key(event)
        if key is None:
            # Private records and older schemas may not retain enough metadata
            # to reconcile safely.  Absence is not evidence of a bad ACK.
            continue
        try:
            sequence = _sequence(event)
        except (TypeError, ValueError):
            sequence = None
        correlation = _correlation(event)
        lifecycle = lifecycles.setdefault(key, _DeliveryLifecycle())
        if kind == "delivery.durable":
            if lifecycle.durable:
                violations.append(
                    ReplayViolation(
                        "delivery.durable_duplicate",
                        f"delivery {key!r} was made durable more than once",
                        sequence,
                        correlation,
                        kind,
                    )
                )
            if lifecycle.acked:
                violations.append(
                    ReplayViolation(
                        "delivery.durable_after_ack",
                        f"delivery {key!r} became durable after its ACK",
                        sequence,
                        correlation,
                        kind,
                    )
                )
            lifecycle.durable += 1
            continue
        if not lifecycle.durable:
            if not allow_prior_durable:
                violations.append(
                    ReplayViolation(
                        "delivery.acked_without_durable",
                        f"delivery {key!r} was ACKed without a preceding durable event",
                        sequence,
                        correlation,
                        kind,
                    )
                )
            # Remember the ACK even when a deliberately selected run may omit
            # its durable predecessor, so duplicate ACKs remain detectable.
        if lifecycle.acked:
            violations.append(
                ReplayViolation(
                    "delivery.acked_duplicate",
                    f"delivery {key!r} was ACKed more than once",
                    sequence,
                    correlation,
                    kind,
                )
            )
        lifecycle.acked += 1
    return tuple(violations)


def replay_events(
    events: Iterable[Mapping[str, Any]],
    *,
    correlation_id: str | None = None,
    trace_id: str | None = None,
    auth_key: bytes | str | None = None,
    _authentication_verified: bool = False,
    _validate_deliveries: bool = True,
    _allow_prior_durable: bool = False,
) -> ReplayReport:
    """Verify and project event envelopes without executing runtime behavior.

    Hash-chain and sequence checks apply to the complete supplied stream, even
    when a correlation/trace filter is selected.  Lifecycle and state projection
    checks apply only to selected events.  Envelopes without hash fields are
    accepted as records already verified by their reader.  Raw HMAC envelopes
    require ``auth_key``; only the internal journal reader may mark them as
    already authenticated.
    """

    normalized_auth_key = _normalize_auth_key(auth_key)
    violations: list[ReplayViolation] = []
    lifecycles: dict[str, _Lifecycle] = {}
    inference_calls: dict[str, _CallLifecycle] = {}
    tool_calls: dict[str, _CallLifecycle] = {}
    redacted_call_stacks: dict[tuple[str, str], list[int | None]] = {}
    delivery_events: list[Mapping[str, Any]] = []
    projections: dict[str, Mapping[str, Any]] = {}
    final_hashes: dict[str, str] = {}
    outcomes: dict[str, str] = {}
    event_kinds: list[str] = []
    seen = 0
    replayed = 0
    first_sequence: int | None = None
    last_sequence: int | None = None
    prior_sequence: int | None = None
    prior_hash: str | None = None

    for ordinal, raw_event in enumerate(events, start=1):
        event = _as_mapping(raw_event, ordinal)
        seen += 1
        kind = _kind(event)
        correlation = _correlation(event)
        try:
            sequence = _sequence(event)
        except (TypeError, ValueError) as exc:
            sequence = None
            violations.append(
                ReplayViolation("sequence.invalid", str(exc), None, correlation, kind)
            )

        if ordinal == 1 and sequence != 1:
            violations.append(
                ReplayViolation(
                    "sequence.first_not_one",
                    f"the first event in a run must have sequence 1, got {sequence!r}",
                    sequence,
                    correlation,
                    kind,
                )
            )
        if sequence is not None:
            if first_sequence is None:
                first_sequence = sequence
            if prior_sequence is not None and sequence != prior_sequence + 1:
                violations.append(
                    ReplayViolation(
                        "sequence.discontinuity",
                        f"expected sequence {prior_sequence + 1}, got {sequence}",
                        sequence,
                        correlation,
                        kind,
                    )
                )
            if prior_sequence is not None and sequence <= prior_sequence:
                violations.append(
                    ReplayViolation(
                        "sequence.non_monotonic",
                        f"sequence {sequence} does not follow {prior_sequence}",
                        sequence,
                        correlation,
                        kind,
                    )
                )
            prior_sequence = sequence
            last_sequence = sequence

        recorded_previous = event.get("previous_hash")
        if (
            ordinal == 1
            and recorded_previous is not None
            and str(recorded_previous) != "0" * 64
        ):
            violations.append(
                ReplayViolation(
                    "hash.genesis_mismatch",
                    "the first event previous_hash is not the journal genesis hash",
                    sequence,
                    correlation,
                    kind,
                )
            )
        if prior_hash is not None and recorded_previous is not None and str(recorded_previous) != prior_hash:
            violations.append(
                ReplayViolation(
                    "hash.previous_mismatch",
                    "previous_hash does not match the preceding event_hash",
                    sequence,
                    correlation,
                    kind,
                )
            )
        recorded_hash = event.get("event_hash")
        hash_algorithm = str(event.get("hash_algorithm", "sha256"))
        if recorded_hash is not None and hash_algorithm not in {
            "sha256",
            "hmac-sha256",
        }:
            violations.append(
                ReplayViolation(
                    "hash.algorithm_invalid",
                    f"unsupported hash algorithm {hash_algorithm!r}",
                    sequence,
                    correlation,
                    kind,
                )
            )
            prior_hash = str(recorded_hash)
        elif (
            recorded_hash is not None
            and hash_algorithm == "hmac-sha256"
            and normalized_auth_key is None
            and not _authentication_verified
        ):
            violations.append(
                ReplayViolation(
                    "hash.authentication_unverified",
                    "HMAC event cannot be authenticated without the journal key",
                    sequence,
                    correlation,
                    kind,
                )
            )
            prior_hash = str(recorded_hash)
        elif recorded_hash is not None and not (
            hash_algorithm == "hmac-sha256" and _authentication_verified
        ):
            try:
                calculated_hash = _event_hash(
                    event,
                    normalized_auth_key if hash_algorithm == "hmac-sha256" else None,
                )
            except Exception as exc:  # recovery tooling must report, not crash
                violations.append(
                    ReplayViolation(
                        "hash.verifier_error",
                        f"event hash verifier failed: {exc}",
                        sequence,
                        correlation,
                        kind,
                    )
                )
            else:
                if not hmac.compare_digest(
                    str(recorded_hash).encode("utf-8"),
                    calculated_hash.encode("ascii"),
                ):
                    violations.append(
                        ReplayViolation(
                            "hash.event_mismatch",
                            "event_hash does not match the canonical envelope",
                            sequence,
                            correlation,
                            kind,
                        )
                    )
            prior_hash = str(recorded_hash)
        elif recorded_hash is not None:
            # EventJournal.iter_events(verify=True) authenticated this HMAC
            # before yielding it.  This path is never used for raw JSONL.
            prior_hash = str(recorded_hash)
        elif "hash_algorithm" in event:
            violations.append(
                ReplayViolation(
                    "hash.event_missing",
                    "hash_algorithm is present but event_hash is missing",
                    sequence,
                    correlation,
                    kind,
                )
            )
            if (
                hash_algorithm == "hmac-sha256"
                and normalized_auth_key is None
                and not _authentication_verified
            ):
                violations.append(
                    ReplayViolation(
                        "hash.authentication_unverified",
                        "HMAC event cannot be authenticated without the journal key",
                        sequence,
                        correlation,
                        kind,
                    )
                )
            prior_hash = None
        else:
            prior_hash = None

        if not _matches(event, correlation_id, trace_id):
            continue
        replayed += 1
        event_kinds.append(kind)

        if kind.startswith(_INTERACTION_PREFIX):
            lifecycle = lifecycles.setdefault(correlation, _Lifecycle())
            if kind == "interaction.accepted":
                explicit_outcome = _explicit_outcome(event)
                if explicit_outcome not in {None, "accepted"}:
                    violations.append(
                        ReplayViolation(
                            "lifecycle.outcome_type_mismatch",
                            f"{kind} cannot have outcome {explicit_outcome!r}",
                            sequence,
                            correlation,
                            kind,
                        )
                    )
                if lifecycle.accepted or lifecycle.started or lifecycle.terminal:
                    violations.append(
                        ReplayViolation(
                            "lifecycle.accepted_out_of_order",
                            "accepted must be the first interaction lifecycle event",
                            sequence,
                            correlation,
                            kind,
                        )
                    )
                lifecycle.accepted += 1
            elif kind == "interaction.started":
                explicit_outcome = _explicit_outcome(event)
                if explicit_outcome not in {None, "started"}:
                    violations.append(
                        ReplayViolation(
                            "lifecycle.outcome_type_mismatch",
                            f"{kind} cannot have outcome {explicit_outcome!r}",
                            sequence,
                            correlation,
                            kind,
                        )
                    )
                if lifecycle.accepted != 1 or lifecycle.terminal:
                    violations.append(
                        ReplayViolation(
                            "lifecycle.started_out_of_order",
                            "started must follow exactly one accepted event",
                            sequence,
                            correlation,
                            kind,
                        )
                    )
                if lifecycle.started:
                    violations.append(
                        ReplayViolation(
                            "lifecycle.started_duplicate",
                            "interaction has more than one started event",
                            sequence,
                            correlation,
                            kind,
                        )
                    )
                lifecycle.started += 1
            elif kind in _TERMINAL_KINDS:
                terminal_outcome = _outcome(event, kind)
                explicit_outcome = _explicit_outcome(event)
                kind_outcome = _TERMINAL_KINDS[kind]
                if kind_outcome == "terminal":
                    compatible = explicit_outcome in {
                        "succeeded",
                        "failed",
                        "cancelled",
                        "rejected",
                    }
                else:
                    compatible = explicit_outcome in {None, kind_outcome}
                if not compatible:
                    violations.append(
                        ReplayViolation(
                            "lifecycle.outcome_type_mismatch",
                            f"{kind} is incompatible with outcome {explicit_outcome!r}",
                            sequence,
                            correlation,
                            kind,
                        )
                    )
                if lifecycle.accepted != 1 and not (
                    terminal_outcome == "rejected"
                    and lifecycle.accepted == 0
                    and lifecycle.started == 0
                ):
                    violations.append(
                        ReplayViolation(
                            "lifecycle.terminal_without_accepted",
                            "terminal event must follow exactly one accepted event",
                            sequence,
                            correlation,
                            kind,
                        )
                    )
                if lifecycle.terminal:
                    violations.append(
                        ReplayViolation(
                            "lifecycle.terminal_duplicate",
                            "interaction has more than one terminal event",
                            sequence,
                            correlation,
                            kind,
                        )
                    )
                lifecycle.terminal += 1
                lifecycle.terminal_outcome = terminal_outcome
                lifecycle.terminal_sequence = sequence
                outcomes[correlation] = lifecycle.terminal_outcome

        if kind in {"inference.started", "inference.finished"}:
            call_id = _call_id(
                event,
                sequence=sequence,
                correlation=correlation,
                kind=kind,
                family="inference",
                violations=violations,
            )
            if call_id is not None:
                stage = kind.rsplit(".", 1)[-1]
                _record_call_event(
                    inference_calls,
                    call_id,
                    stage=stage,
                    family="inference",
                    sequence=sequence,
                    correlation=correlation,
                    kind=kind,
                    violations=violations,
                )
            elif _is_redacted_private_call(event):
                _record_redacted_call_event(
                    redacted_call_stacks,
                    stage=kind.rsplit(".", 1)[-1],
                    family="inference",
                    sequence=sequence,
                    correlation=correlation,
                    kind=kind,
                    violations=violations,
                )
        elif kind in {"tool.started", "tool.finished"}:
            call_id = _call_id(
                event,
                sequence=sequence,
                correlation=correlation,
                kind=kind,
                family="tool",
                violations=violations,
            )
            if call_id is not None:
                stage = kind.rsplit(".", 1)[-1]
                _record_call_event(
                    tool_calls,
                    call_id,
                    stage=stage,
                    family="tool",
                    sequence=sequence,
                    correlation=correlation,
                    kind=kind,
                    violations=violations,
                )
            elif _is_redacted_private_call(event):
                _record_redacted_call_event(
                    redacted_call_stacks,
                    stage=kind.rsplit(".", 1)[-1],
                    family="tool",
                    sequence=sequence,
                    correlation=correlation,
                    kind=kind,
                    violations=violations,
                )
        elif kind in {"delivery.durable", "delivery.acked"}:
            delivery_events.append(event)

        payload = event.get("payload")
        if (
            kind in {"state.snapshot", "state.delta"}
            and event.get("privacy") == "private_ephemeral"
            and (payload is None or payload == {})
        ):
            # `/local` journal records are deliberately content/state-redacted.
            # Their lifecycle remains auditable, but there is nothing to project.
            continue
        if kind == "state.snapshot":
            if not isinstance(payload, Mapping) or not isinstance(payload.get("projection"), Mapping):
                violations.append(
                    ReplayViolation(
                        "state.snapshot_invalid",
                        "state.snapshot requires payload.projection object",
                        sequence,
                        correlation,
                        kind,
                    )
                )
                continue
            projection = copy.deepcopy(dict(payload["projection"]))
            try:
                calculated = _projection_hash(projection)
            except Exception as exc:
                violations.append(
                    ReplayViolation(
                        "state.hash_error",
                        f"could not hash state snapshot: {exc}",
                        sequence,
                        correlation,
                        kind,
                    )
                )
                continue
            expected = payload.get("projection_hash")
            snapshot_is_valid = True
            if expected is not None and str(expected) != calculated:
                snapshot_is_valid = False
                violations.append(
                    ReplayViolation(
                        "state.snapshot_hash_mismatch",
                        "projection_hash does not match state.snapshot projection",
                        sequence,
                        correlation,
                        kind,
                    )
                )
            for invariant in _projection_invariants(projection):
                snapshot_is_valid = False
                violations.append(
                    ReplayViolation(
                        "state.invariant",
                        invariant,
                        sequence,
                        correlation,
                        kind,
                    )
                )
            if snapshot_is_valid:
                projections[correlation] = projection
                final_hashes[correlation] = calculated
        elif kind == "state.delta":
            if not isinstance(payload, Mapping) or "patch" not in payload:
                violations.append(
                    ReplayViolation(
                        "state.delta_invalid",
                        "state.delta requires payload.patch",
                        sequence,
                        correlation,
                        kind,
                    )
                )
                continue
            projection = projections.get(correlation)
            if projection is None:
                violations.append(
                    ReplayViolation(
                        "state.delta_without_snapshot",
                        "state.delta has no preceding state.snapshot for this correlation",
                        sequence,
                        correlation,
                        kind,
                    )
                )
                continue
            before_hash = _projection_hash(projection)
            expected_before = payload.get("before_hash")
            if expected_before is not None and str(expected_before) != before_hash:
                violations.append(
                    ReplayViolation(
                        "state.before_hash_mismatch",
                        "before_hash does not match the current projection",
                        sequence,
                        correlation,
                        kind,
                    )
                )
                continue
            try:
                next_projection = _apply_projection_patch(projection, payload["patch"])
                after_hash = _projection_hash(next_projection)
            except Exception as exc:
                violations.append(
                    ReplayViolation(
                        "state.patch_invalid",
                        f"state delta patch failed: {exc}",
                        sequence,
                        correlation,
                        kind,
                    )
                )
                continue
            expected_after = payload.get("after_hash")
            if expected_after is not None and str(expected_after) != after_hash:
                violations.append(
                    ReplayViolation(
                        "state.after_hash_mismatch",
                        "after_hash does not match the patched projection",
                        sequence,
                        correlation,
                        kind,
                    )
                )
                continue
            invariants = _projection_invariants(next_projection)
            if invariants:
                for invariant in invariants:
                    violations.append(
                        ReplayViolation(
                            "state.invariant",
                            invariant,
                            sequence,
                            correlation,
                            kind,
                        )
                    )
                continue
            projections[correlation] = copy.deepcopy(dict(next_projection))
            final_hashes[correlation] = after_hash

    for correlation, lifecycle in lifecycles.items():
        rejected_before_admission = (
            lifecycle.terminal_outcome == "rejected"
            and lifecycle.accepted == 0
            and lifecycle.started == 0
            and lifecycle.terminal == 1
        )
        if lifecycle.accepted != 1 and not rejected_before_admission:
            violations.append(
                ReplayViolation(
                    "lifecycle.accepted_count",
                    f"interaction requires exactly one accepted event; got {lifecycle.accepted}",
                    correlation_id=correlation,
                )
            )
        if lifecycle.terminal_outcome in {"succeeded", "failed"}:
            expected_started = "requires exactly one"
            invalid_started = lifecycle.started != 1
        elif lifecycle.terminal_outcome == "rejected":
            expected_started = "requires no"
            invalid_started = lifecycle.started != 0
        else:
            expected_started = "permits at most one"
            invalid_started = lifecycle.started > 1
        if invalid_started:
            violations.append(
                ReplayViolation(
                    "lifecycle.started_count",
                    f"{lifecycle.terminal_outcome or 'unterminated'} interaction "
                    f"{expected_started} started event; got {lifecycle.started}",
                    correlation_id=correlation,
                )
            )
        if lifecycle.terminal_outcome == "rejected" and lifecycle.accepted != 0:
            violations.append(
                ReplayViolation(
                    "lifecycle.rejected_after_admission",
                    "rejected interaction must be a pre-admission terminal",
                    lifecycle.terminal_sequence,
                    correlation,
                )
            )
        if lifecycle.terminal != 1:
            violations.append(
                ReplayViolation(
                    "lifecycle.terminal_count",
                    f"interaction requires exactly one terminal event; got {lifecycle.terminal}",
                    correlation_id=correlation,
                )
            )

    for family, call_lifecycles in (
        ("inference", inference_calls),
        ("tool", tool_calls),
    ):
        for call_id, lifecycle in call_lifecycles.items():
            if lifecycle.started != 1:
                violations.append(
                    ReplayViolation(
                        f"{family}.started_count",
                        f"call {call_id!r} requires exactly one start; got {lifecycle.started}",
                        lifecycle.finished_sequence,
                    )
                )
            if lifecycle.finished != 1:
                violations.append(
                    ReplayViolation(
                        f"{family}.finished_count",
                        f"call {call_id!r} requires exactly one finish; got {lifecycle.finished}",
                        lifecycle.started_sequence,
                    )
                )

    for (family, correlation), open_calls in redacted_call_stacks.items():
        for started_sequence in open_calls:
            violations.append(
                ReplayViolation(
                    f"{family}.finished_count",
                    "redacted private call has no terminal event",
                    started_sequence,
                    correlation,
                    f"{family}.started",
                )
            )

    if _validate_deliveries:
        violations.extend(
            _delivery_violations(
                delivery_events,
                allow_prior_durable=_allow_prior_durable,
            )
        )

    frozen_projections = {
        key: copy.deepcopy(dict(value)) for key, value in projections.items()
    }
    return ReplayReport(
        valid=not violations,
        events_seen=seen,
        events_replayed=replayed,
        first_sequence=first_sequence,
        last_sequence=last_sequence,
        event_kinds=tuple(event_kinds),
        outcomes=dict(outcomes),
        final_projections=frozen_projections,
        final_hashes=dict(final_hashes),
        violations=tuple(violations),
        selected_correlation_id=correlation_id,
        selected_trace_id=trace_id,
        runs_replayed=1 if seen else 0,
    )


def evaluate_scenario(
    report: ReplayReport, expectations: Mapping[str, Any]
) -> ScenarioEvaluation:
    """Compare replay output with deterministic JSON-friendly expectations.

    Supported keys are ``event_kinds`` (exact ordered sequence),
    ``contains_event_kinds`` (ordered subsequence), ``outcome`` (single selected
    trace), ``outcomes`` (correlation-to-outcome mapping), ``final_hash`` and
    ``final_hashes``.
    """

    if not isinstance(expectations, Mapping):
        raise ReplayError("scenario expectations must be a JSON object")
    violations: list[ReplayViolation] = []

    exact_kinds = expectations.get("event_kinds", expectations.get("kinds"))
    if exact_kinds is not None:
        if isinstance(exact_kinds, (str, bytes)) or not isinstance(exact_kinds, Sequence):
            raise ReplayError("event_kinds expectation must be an array")
        expected = tuple(str(kind) for kind in exact_kinds)
        if expected != report.event_kinds:
            violations.append(
                ReplayViolation(
                    "scenario.event_kinds",
                    f"expected event kinds {list(expected)!r}, got {list(report.event_kinds)!r}",
                )
            )

    contains = expectations.get("contains_event_kinds")
    if contains is not None:
        if isinstance(contains, (str, bytes)) or not isinstance(contains, Sequence):
            raise ReplayError("contains_event_kinds expectation must be an array")
        expected = [str(kind) for kind in contains]
        cursor = 0
        for kind in report.event_kinds:
            if cursor < len(expected) and kind == expected[cursor]:
                cursor += 1
        if cursor != len(expected):
            violations.append(
                ReplayViolation(
                    "scenario.missing_event_kinds",
                    f"expected ordered subsequence {expected!r}",
                )
            )

    expected_outcome = expectations.get("outcome")
    if expected_outcome is not None:
        actual_outcome = None
        if report.selected_correlation_id is not None:
            actual_outcome = report.outcomes.get(report.selected_correlation_id)
        elif (
            report.selected_trace_id is not None
            and report.selected_trace_id in report.outcomes
        ):
            actual_outcome = report.outcomes[report.selected_trace_id]
        elif len(report.outcomes) == 1:
            actual_outcome = next(iter(report.outcomes.values()))
        if str(expected_outcome) != actual_outcome:
            violations.append(
                ReplayViolation(
                    "scenario.outcome",
                    f"expected outcome {expected_outcome!r}, got {actual_outcome!r}",
                )
            )

    expected_outcomes = expectations.get("outcomes")
    if expected_outcomes is not None:
        if not isinstance(expected_outcomes, Mapping):
            raise ReplayError("outcomes expectation must be an object")
        for correlation, expected in expected_outcomes.items():
            actual = report.outcomes.get(str(correlation))
            if str(expected) != actual:
                violations.append(
                    ReplayViolation(
                        "scenario.outcomes",
                        f"expected outcome {expected!r}, got {actual!r}",
                        correlation_id=str(correlation),
                    )
                )

    expected_final = expectations.get("final_hash")
    if expected_final is not None and str(expected_final) != report.final_hash:
        violations.append(
            ReplayViolation(
                "scenario.final_hash",
                f"expected final hash {expected_final!r}, got {report.final_hash!r}",
            )
        )

    expected_finals = expectations.get("final_hashes")
    if expected_finals is not None:
        if not isinstance(expected_finals, Mapping):
            raise ReplayError("final_hashes expectation must be an object")
        for correlation, expected in expected_finals.items():
            actual = report.final_hashes.get(str(correlation))
            if str(expected) != actual:
                violations.append(
                    ReplayViolation(
                        "scenario.final_hashes",
                        f"expected final hash {expected!r}, got {actual!r}",
                        correlation_id=str(correlation),
                    )
                )

    return ScenarioEvaluation(passed=not violations, violations=tuple(violations))


def _jsonl_events(path: Path) -> Iterator[Mapping[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ReplayError(f"invalid JSON at {path}:{line_number}: {exc}") from exc
                if not isinstance(event, Mapping):
                    raise ReplayError(f"event at {path}:{line_number} is not an object")
                yield event
    except OSError as exc:
        raise ReplayError(f"cannot read {path}: {exc}") from exc


def _construct_journal(
    journal_type: type[Any], root: Path, run_id: str | None = None
) -> Any:
    """Instantiate common EventJournal constructor shapes without runtime imports."""

    try:
        parameters = inspect.signature(journal_type).parameters
    except (TypeError, ValueError):
        parameters = {}
    kwargs: dict[str, Any] = {}
    if run_id is not None and "run_id" in parameters:
        kwargs["run_id"] = run_id
        if "create" in parameters:
            kwargs["create"] = False
    if "auth_key" in parameters:
        auth_key = _configured_auth_key()
        if auth_key is not None:
            kwargs["auth_key"] = auth_key
    for name in ("root", "journal_root", "root_dir", "path", "directory"):
        if name in parameters:
            kwargs[name] = root
            return journal_type(**kwargs)
    return journal_type(root, **kwargs)


def _reader_mappings(reader: Iterable[Any]) -> Iterator[Mapping[str, Any]]:
    try:
        for ordinal, event in enumerate(reader, start=1):
            yield _as_mapping(event, ordinal)
    except ReplayError:
        raise
    except Exception as exc:
        raise ReplayError(f"event-journal reader failed: {exc}") from exc


def _iter_journal_runs(
    root: Path,
) -> list[tuple[str, Iterable[Mapping[str, Any]], bool]]:
    if root.is_file():
        return [(root.name, _jsonl_events(root), False)]
    try:
        from core import event_journal as journal_module
    except ImportError as exc:
        raise ReplayError(
            "core.event_journal is unavailable; pass a JSONL file or install the journal module"
        ) from exc

    module_reader = getattr(journal_module, "iter_events", None)
    if callable(module_reader):
        return [(str(root), _reader_mappings(module_reader(root)), False)]
    journal_type = getattr(journal_module, "EventJournal", None)
    if journal_type is None:
        raise ReplayError("core.event_journal does not expose EventJournal or iter_events")

    resolved = root.expanduser().resolve()
    if resolved.name == "events" and resolved.parent.parent.name == "runs":
        journal_root = resolved.parent.parent.parent
        run_ids = (resolved.parent.name,)
    elif resolved.parent.name == "runs" and (resolved / "events").is_dir():
        journal_root = resolved.parent.parent
        run_ids = (resolved.name,)
    elif resolved.name == "runs" and resolved.is_dir():
        journal_root = resolved.parent
        list_runs = getattr(journal_type, "list_run_ids", None)
        if not callable(list_runs):
            raise ReplayError("EventJournal does not expose list_run_ids()")
        try:
            run_ids = tuple(list_runs(journal_root))
        except Exception as exc:
            raise ReplayError(
                f"cannot enumerate event journal runs at {root}: {exc}"
            ) from exc
    else:
        journal_root = resolved
        list_runs = getattr(journal_type, "list_run_ids", None)
        if not callable(list_runs):
            raise ReplayError("EventJournal does not expose list_run_ids()")
        try:
            run_ids = tuple(list_runs(journal_root))
        except Exception as exc:
            raise ReplayError(f"cannot enumerate event journal runs at {root}: {exc}") from exc
    if not run_ids:
        raise ReplayError(f"no journal runs found below {root}")

    runs: list[tuple[str, Iterable[Mapping[str, Any]], bool]] = []
    for run_id in run_ids:
        try:
            journal = _construct_journal(journal_type, journal_root, str(run_id))
        except Exception as exc:
            raise ReplayError(
                f"cannot open event journal run {run_id!r} at {journal_root}: {exc}"
            ) from exc
        reader = getattr(journal, "iter_events", None)
        if not callable(reader):
            raise ReplayError("EventJournal does not expose iter_events()")
        try:
            parameters = inspect.signature(reader).parameters
        except (TypeError, ValueError):
            parameters = {}
        raw_reader = reader(verify=True) if "verify" in parameters else reader()
        runs.append((str(run_id), _reader_mappings(raw_reader), True))
    return runs


def _iter_journal_events(root: Path) -> Iterable[Mapping[str, Any]]:
    """Compatibility reader for a JSONL file or one explicitly selected run."""

    runs = _iter_journal_runs(root)
    if len(runs) != 1:
        raise ReplayError(
            "journal root contains multiple runs; replay each run independently"
        )
    return runs[0][1]


def _combine_reports(
    reports: Sequence[ReplayReport],
    additional_violations: Sequence[ReplayViolation] = (),
) -> ReplayReport:
    if not reports:
        raise ReplayError("event journal did not expose any runs")
    violations: list[ReplayViolation] = []
    kinds: list[str] = []
    outcomes: dict[str, str] = {}
    projections: dict[str, Mapping[str, Any]] = {}
    hashes: dict[str, str] = {}
    for report in reports:
        violations.extend(report.violations)
        kinds.extend(report.event_kinds)
        outcomes.update(report.outcomes)
        projections.update(report.final_projections)
        hashes.update(report.final_hashes)
    violations.extend(additional_violations)
    return ReplayReport(
        valid=not violations,
        events_seen=sum(report.events_seen for report in reports),
        events_replayed=sum(report.events_replayed for report in reports),
        first_sequence=reports[0].first_sequence,
        last_sequence=reports[-1].last_sequence,
        event_kinds=tuple(kinds),
        outcomes=outcomes,
        final_projections=projections,
        final_hashes=hashes,
        violations=tuple(violations),
        selected_correlation_id=reports[0].selected_correlation_id,
        selected_trace_id=reports[0].selected_trace_id,
        runs_replayed=len(reports),
    )


def _replay_journal(
    root: Path,
    *,
    correlation_id: str | None = None,
    trace_id: str | None = None,
) -> ReplayReport:
    reports: list[ReplayReport] = []
    delivery_events: list[Mapping[str, Any]] = []
    auth_key = _configured_auth_key()
    for _run_id, events, authentication_verified in _iter_journal_runs(root):
        materialized = list(events)
        delivery_events.extend(materialized)
        reports.append(
            replay_events(
                materialized,
                correlation_id=correlation_id,
                trace_id=trace_id,
                auth_key=None if authentication_verified else auth_key,
                _authentication_verified=authentication_verified,
                _validate_deliveries=False,
            )
        )

    resolved = root.expanduser().resolve()
    selected_single_run = (
        (resolved.name == "events" and resolved.parent.parent.name == "runs")
        or (resolved.parent.name == "runs" and (resolved / "events").is_dir())
        or resolved.is_file()
    )
    delivery_violations = _delivery_violations(
        delivery_events,
        correlation_id=correlation_id,
        trace_id=trace_id,
        allow_prior_durable=selected_single_run,
    )
    return _combine_reports(reports, delivery_violations)


def _load_expectations(path: Path) -> Mapping[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ReplayError(f"cannot load expectation file {path}: {exc}") from exc
    if not isinstance(value, Mapping):
        raise ReplayError("expectation file must contain one JSON object")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m core.replay",
        description="Verify and replay an Aura event journal without runtime side effects.",
    )
    parser.add_argument("journal_root", type=Path, metavar="JOURNAL_ROOT")
    parser.add_argument("--correlation", dest="correlation_id")
    parser.add_argument("--trace", dest="trace_id")
    parser.add_argument("--expect", type=Path, dest="expectation_path")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
        report = _replay_journal(
            args.journal_root,
            correlation_id=args.correlation_id,
            trace_id=args.trace_id,
        )
        evaluation = None
        if args.expectation_path is not None:
            evaluation = evaluate_scenario(report, _load_expectations(args.expectation_path))
    except ReplayError as exc:
        print(f"replay error: {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError, TypeError) as exc:
        print(f"replay error: {exc}", file=sys.stderr)
        return 2

    passed = report.valid and (evaluation is None or evaluation.passed)
    if args.as_json:
        output: dict[str, Any] = {"report": report.to_dict()}
        if evaluation is not None:
            output["scenario"] = evaluation.to_dict()
        print(json.dumps(output, sort_keys=True, ensure_ascii=False))
    else:
        print(
            f"{'VALID' if passed else 'INVALID'}: "
            f"replayed {report.events_replayed}/{report.events_seen} events, "
            f"{len(report.violations)} replay violation(s)"
        )
        for violation in report.violations:
            print(f"- {violation.code}: {violation.message}")
        if evaluation is not None:
            for violation in evaluation.violations:
                print(f"- {violation.code}: {violation.message}")
    if passed:
        return 0
    corruption = any(
        violation.code.startswith(("hash.", "sequence."))
        for violation in report.violations
    )
    return 2 if corruption else 1


if __name__ == "__main__":  # pragma: no cover - exercised through the CLI
    raise SystemExit(main())
