"""Equation helpers for Emotion V2.  They are pure and deterministic."""

from __future__ import annotations

import math
from typing import Sequence


def dot(left: Sequence[float], right: Sequence[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


def sigmoid(value: float) -> float:
    # The two branches avoid unnecessary overflow while preserving IEEE doubles.
    if value >= 0.0:
        return 1.0 / (1.0 + math.exp(-value))
    exponent = math.exp(value)
    return exponent / (1.0 + exponent)


def activation_to_latent(activation: float, epsilon: float) -> float:
    """The specified bounded-logit transform (with finite endpoint handling)."""
    if activation <= epsilon:
        activation = math.nextafter(epsilon, math.inf)
    elif activation >= 1.0 - epsilon:
        activation = math.nextafter(1.0 - epsilon, -math.inf)
    return math.log((activation - epsilon) / (1.0 - epsilon - activation))


def latent_to_activation(latent: float, epsilon: float) -> float:
    return epsilon + (1.0 - 2.0 * epsilon) * sigmoid(latent)


def bounded_target(raw_target: float, epsilon: float) -> tuple[float, float]:
    target = latent_to_activation(raw_target, epsilon)
    return target, activation_to_latent(target, epsilon)
