"""Frozen value objects for the pure Emotion V2 reducer.

This module deliberately has no knowledge of durable receipts, clocks, or the
legacy self model.  Callers supply an already-made novelty decision.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
import hashlib
import json
import math
from typing import Any, Iterable, Sequence


COMPONENT_ORDER = ("joy", "sadness", "fear", "anger", "interest", "calm")
APPRAISAL_ORDER = (
    "valence", "goal_congruence", "novelty", "threat", "controllability",
    "agency_self_other", "social_relevance", "norm_conflict", "arousal",
)
DRIVE_ORDER = ("fatigue", "energy_deficit", "social_need", "curiosity")
TRAIT_ORDER = (
    "negative_sensitivity", "reward_sensitivity", "recovery_rate",
    "novelty_seeking", "affiliation",
)
MEMORY_SUMMARY_ORDER = (
    "dose_weighted_valence", "dose_weighted_arousal", "dose_confidence", "dose",
)


class EmotionValidationError(ValueError):
    """Raised when a reducer boundary contract is not met."""


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EmotionValidationError(f"{name} must be a non-boolean finite number")
    result = float(value)
    if not math.isfinite(result):
        raise EmotionValidationError(f"{name} must be finite")
    return result


def _integer(value: object, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise EmotionValidationError(f"{name} must be an integer >= {minimum}")
    return value


def _vector(
    value: Sequence[object], name: str, size: int, lower: float | None = None,
    upper: float | None = None,
) -> tuple[float, ...]:
    if isinstance(value, (str, bytes)):
        raise EmotionValidationError(f"{name} must be a {size}-element sequence")
    try:
        result = tuple(_number(item, f"{name}[{index}]") for index, item in enumerate(value))
    except TypeError as exc:
        raise EmotionValidationError(f"{name} must be a {size}-element sequence") from exc
    if len(result) != size:
        raise EmotionValidationError(f"{name} must have exactly {size} elements")
    if lower is not None and any(item < lower for item in result):
        raise EmotionValidationError(f"{name} values must be >= {lower}")
    if upper is not None and any(item > upper for item in result):
        raise EmotionValidationError(f"{name} values must be <= {upper}")
    return result


def _json_value(value: Any) -> Any:
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    return value


def canonical_json_bytes(value: Any) -> bytes:
    """Return deterministic, finite UTF-8 JSON suitable for a state hash."""
    try:
        return json.dumps(
            _json_value(value), sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise EmotionValidationError("value cannot be represented as canonical finite JSON") from exc


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


@dataclass(frozen=True, slots=True)
class EmotionStateV2:
    activations: Sequence[object]
    velocity: Sequence[object]
    mood: object
    uncertainty: object
    last_update_ns: object
    event_sequence: object
    parameter_set_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.parameter_set_id, str) or not self.parameter_set_id:
            raise EmotionValidationError("parameter_set_id must be non-empty")
        activations = _vector(self.activations, "activations", 6, 0.0, 1.0)
        velocity = _vector(self.velocity, "velocity", 6)
        mood = _number(self.mood, "mood")
        uncertainty = _number(self.uncertainty, "uncertainty")
        if not -1.0 <= mood <= 1.0:
            raise EmotionValidationError("mood must be in [-1, 1]")
        if not 0.0 <= uncertainty <= 1.0:
            raise EmotionValidationError("uncertainty must be in [0, 1]")
        object.__setattr__(self, "activations", activations)
        object.__setattr__(self, "velocity", velocity)
        object.__setattr__(self, "mood", mood)
        object.__setattr__(self, "uncertainty", uncertainty)
        object.__setattr__(self, "last_update_ns", _integer(self.last_update_ns, "last_update_ns"))
        object.__setattr__(self, "event_sequence", _integer(self.event_sequence, "event_sequence"))

    def canonical_hash(self) -> str:
        return canonical_sha256(self)


@dataclass(frozen=True, slots=True)
class AppraisalInputV2:
    """Already-fused appraisal values used by B1; fusion itself belongs to B2."""

    values: Sequence[object]
    confidence: object
    uncertainty: object

    def __post_init__(self) -> None:
        values = _vector(self.values, "appraisal.values", 9)
        for index, item in enumerate(values):
            lower, upper = (-1.0, 1.0) if index in (0, 1, 5) else (0.0, 1.0)
            if not lower <= item <= upper:
                raise EmotionValidationError(f"appraisal.values[{index}] is out of range")
        confidence = _number(self.confidence, "appraisal.confidence")
        uncertainty = _number(self.uncertainty, "appraisal.uncertainty")
        if not 0.0 <= confidence <= 1.0 or not 0.0 <= uncertainty <= 1.0:
            raise EmotionValidationError("appraisal confidence and uncertainty must be in [0, 1]")
        object.__setattr__(self, "values", values)
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "uncertainty", uncertainty)


@dataclass(frozen=True, slots=True)
class EmotionTransitionV2:
    """All non-durable inputs to exactly one deterministic reduction."""

    appraisal: AppraisalInputV2
    drives: Sequence[object]
    traits: Sequence[object]
    memory_summary_vector: Sequence[object]
    has_event: bool
    is_novel_event: bool
    elapsed_seconds: object
    wall_clock_ns: object

    def __post_init__(self) -> None:
        if not isinstance(self.appraisal, AppraisalInputV2):
            raise EmotionValidationError("appraisal must be AppraisalInputV2")
        if not isinstance(self.has_event, bool) or not isinstance(self.is_novel_event, bool):
            raise EmotionValidationError("has_event and is_novel_event must be bool")
        if self.is_novel_event and not self.has_event:
            raise EmotionValidationError("a novel event must be an event")
        object.__setattr__(self, "drives", _vector(self.drives, "drives", 4, 0.0, 1.0))
        object.__setattr__(self, "traits", _vector(self.traits, "traits", 5, 0.0, 2.0))
        memory = _vector(self.memory_summary_vector, "memory_summary_vector", 4)
        # This is the exact B5 summary vector, not a B1 receipt/DTO.
        if not (-0.20 <= memory[0] <= 0.20 and 0.0 <= memory[1] <= 0.20
                and 0.0 <= memory[2] <= 0.20 and 0.0 <= memory[3] <= 0.20):
            raise EmotionValidationError("memory_summary_vector is not a valid four-element summary")
        dose = memory[3]
        if (abs(memory[0]) > dose or memory[1] > dose or memory[2] > dose
                or (dose == 0.0 and memory != (0.0, 0.0, 0.0, 0.0))):
            raise EmotionValidationError("memory_summary_vector components must not exceed total dose")
        object.__setattr__(self, "memory_summary_vector", memory)
        elapsed = _number(self.elapsed_seconds, "elapsed_seconds")
        if elapsed < 0.0:
            raise EmotionValidationError("elapsed_seconds must be non-negative")
        object.__setattr__(self, "elapsed_seconds", elapsed)
        object.__setattr__(self, "wall_clock_ns", _integer(self.wall_clock_ns, "wall_clock_ns"))

    def canonical_hash(self) -> str:
        return canonical_sha256(self)
