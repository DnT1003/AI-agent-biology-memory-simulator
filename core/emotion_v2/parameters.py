"""Validated, versioned parameters for the Emotion V2 mathematical kernel."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence

from .types import EmotionValidationError, _number, _vector, canonical_sha256


def _matrix(value: Sequence[Sequence[object]], name: str, rows: int, columns: int) -> tuple[tuple[float, ...], ...]:
    if isinstance(value, (str, bytes)):
        raise EmotionValidationError(f"{name} must be a {rows}x{columns} matrix")
    try:
        result = tuple(_vector(row, f"{name}[{index}]", columns) for index, row in enumerate(value))
    except TypeError as exc:
        raise EmotionValidationError(f"{name} must be a {rows}x{columns} matrix") from exc
    if len(result) != rows:
        raise EmotionValidationError(f"{name} must have exactly {rows} rows")
    return result


@dataclass(frozen=True, slots=True)
class EmotionParametersV2:
    parameter_set_id: str
    epsilon: object
    omega: Sequence[object]
    max_substep_seconds: object
    baseline_bias: Sequence[object]
    w_drive: Sequence[Sequence[object]]
    w_trait: Sequence[Sequence[object]]
    k: Sequence[Sequence[object]]
    w_appraisal: Sequence[Sequence[object]]
    w_memory: Sequence[Sequence[object]]
    trait_mood: object
    w_mood_emotion: Sequence[object]
    w_mood_drive: Sequence[object]
    uncertainty_baseline: object
    tau_mood: object
    tau_uncertainty: object
    event_impulse_cap: object
    g_encode_max: object

    def __post_init__(self) -> None:
        if not isinstance(self.parameter_set_id, str) or not self.parameter_set_id:
            raise EmotionValidationError("parameter_set_id must be non-empty")
        epsilon = _number(self.epsilon, "epsilon")
        if not 0.0 < epsilon < 0.01:
            raise EmotionValidationError("epsilon must be in (0, 0.01)")
        omega = _vector(self.omega, "omega", 6)
        if any(item <= 0.0 for item in omega):
            raise EmotionValidationError("omega values must be positive")
        max_substep = _number(self.max_substep_seconds, "max_substep_seconds")
        if max_substep <= 0.0:
            raise EmotionValidationError("max_substep_seconds must be positive")
        baseline = _vector(self.baseline_bias, "baseline_bias", 6)
        w_drive = _matrix(self.w_drive, "w_drive", 6, 4)
        w_trait = _matrix(self.w_trait, "w_trait", 6, 5)
        k = _matrix(self.k, "k", 6, 6)
        if any(sum(abs(item) for item in row) >= 4.0 for row in k):
            raise EmotionValidationError("each absolute K row sum must be < 4.0")
        w_appraisal = _matrix(self.w_appraisal, "w_appraisal", 6, 9)
        w_memory = _matrix(self.w_memory, "w_memory", 6, 4)
        trait_mood = _number(self.trait_mood, "trait_mood")
        w_mood_emotion = _vector(self.w_mood_emotion, "w_mood_emotion", 6)
        w_mood_drive = _vector(self.w_mood_drive, "w_mood_drive", 4)
        uncertainty_baseline = _number(self.uncertainty_baseline, "uncertainty_baseline")
        if not 0.0 <= uncertainty_baseline <= 1.0:
            raise EmotionValidationError("uncertainty_baseline must be in [0, 1]")
        tau_mood = _number(self.tau_mood, "tau_mood")
        tau_uncertainty = _number(self.tau_uncertainty, "tau_uncertainty")
        cap = _number(self.event_impulse_cap, "event_impulse_cap")
        g_encode = _number(self.g_encode_max, "g_encode_max")
        if tau_mood <= 0.0 or tau_uncertainty <= 0.0 or cap <= 0.0:
            raise EmotionValidationError("time constants and event_impulse_cap must be positive")
        if not 0.0 <= g_encode <= 1.0:
            raise EmotionValidationError("g_encode_max must be in [0, 1]")
        memory_inf_norm = max(sum(abs(item) for item in row) for row in w_memory)
        if memory_inf_norm > 1.0:
            raise EmotionValidationError("initial W_memory infinity norm must be <= 1.0")
        loop_gain = g_encode * 0.08 * (0.20 * memory_inf_norm)
        if loop_gain > 0.25:
            raise EmotionValidationError("configured emotion-memory loop gain exceeds 0.25")
        for name, value in (
            ("epsilon", epsilon), ("omega", omega), ("max_substep_seconds", max_substep),
            ("baseline_bias", baseline), ("w_drive", w_drive), ("w_trait", w_trait),
            ("k", k), ("w_appraisal", w_appraisal), ("w_memory", w_memory),
            ("trait_mood", trait_mood), ("w_mood_emotion", w_mood_emotion),
            ("w_mood_drive", w_mood_drive), ("uncertainty_baseline", uncertainty_baseline),
            ("tau_mood", tau_mood), ("tau_uncertainty", tau_uncertainty),
            ("event_impulse_cap", cap), ("g_encode_max", g_encode),
        ):
            object.__setattr__(self, name, value)

    @property
    def memory_infinity_norm(self) -> float:
        return max(sum(abs(item) for item in row) for row in self.w_memory)

    @property
    def configured_loop_gain(self) -> float:
        return self.g_encode_max * 0.08 * (0.20 * self.memory_infinity_norm)

    def canonical_hash(self) -> str:
        return canonical_sha256(self)
