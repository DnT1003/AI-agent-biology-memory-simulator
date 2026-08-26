"""Checked equation helpers for the pure, deterministic Emotion V2 reducer."""

from __future__ import annotations

import math
from typing import Sequence

from .types import EmotionValidationError


def finite(value: float, label: str) -> float:
    if not math.isfinite(value):
        raise EmotionValidationError(f"{label} must remain finite")
    return value


def add(left: float, right: float, label: str) -> float:
    return finite(left + right, label)


def subtract(left: float, right: float, label: str) -> float:
    return finite(left - right, label)


def multiply(left: float, right: float, label: str) -> float:
    return finite(left * right, label)


def negate(value: float, label: str) -> float:
    return finite(-value, label)


def divide(left: float, right: float, label: str) -> float:
    try:
        return finite(left / right, label)
    except (OverflowError, ValueError, ZeroDivisionError) as exc:
        raise EmotionValidationError(f"{label} is invalid") from exc


def exp(value: float, label: str) -> float:
    try:
        return finite(math.exp(value), label)
    except (OverflowError, ValueError) as exc:
        raise EmotionValidationError(f"{label} is invalid") from exc


def log(value: float, label: str) -> float:
    try:
        return finite(math.log(value), label)
    except (OverflowError, ValueError) as exc:
        raise EmotionValidationError(f"{label} is invalid") from exc


def dot(left: Sequence[float], right: Sequence[float], label: str = "dot") -> float:
    """Sequential binary64 dot product with every product and sum checked."""
    total = 0.0
    for index, (first, second) in enumerate(zip(left, right, strict=True)):
        product = multiply(first, second, f"{label}[{index}] product")
        total = add(total, product, f"{label}[{index}] sum")
    return total


def sigmoid(value: float) -> float:
    finite(value, "sigmoid input")
    if value >= 0.0:
        denominator = add(1.0, exp(-value, "sigmoid exponent"), "sigmoid denominator")
        return divide(1.0, denominator, "sigmoid result")
    exponent = exp(value, "sigmoid exponent")
    denominator = add(1.0, exponent, "sigmoid denominator")
    return divide(exponent, denominator, "sigmoid result")


def activation_to_latent(activation: float, epsilon: float) -> float:
    """The bounded-logit transform with finite exact-endpoint handling."""
    finite(activation, "activation")
    finite(epsilon, "epsilon")
    if activation <= epsilon:
        activation = math.nextafter(epsilon, math.inf)
    elif activation >= 1.0 - epsilon:
        activation = math.nextafter(1.0 - epsilon, -math.inf)
    numerator = subtract(activation, epsilon, "latent numerator")
    denominator = subtract(subtract(1.0, epsilon, "latent upper"), activation, "latent denominator")
    return log(divide(numerator, denominator, "latent ratio"), "latent result")


def latent_to_activation(latent: float, epsilon: float) -> float:
    span = subtract(1.0, multiply(2.0, epsilon, "activation epsilon span"), "activation span")
    return add(epsilon, multiply(span, sigmoid(latent), "activation scaled sigmoid"), "activation result")


def bounded_target(raw_target: float, epsilon: float) -> tuple[float, float]:
    target = latent_to_activation(raw_target, epsilon)
    return target, activation_to_latent(target, epsilon)
