"""The bounded deterministic Emotion V2 control reducer."""

from __future__ import annotations

from dataclasses import replace
import math

from .dynamics import (
    activation_to_latent, add, divide, dot, exp, finite, latent_to_activation,
    multiply, negate, subtract,
)
from .parameters import EmotionParametersV2
from .types import (
    _SIGNED_INT64_MAX, EmotionStateV2, EmotionTransitionV2, EmotionValidationError,
    canonical_sha256,
)


def _validate_state_for_parameters(state: EmotionStateV2, parameters: EmotionParametersV2) -> None:
    if state.parameter_set_id != parameters.parameter_set_id:
        raise EmotionValidationError("state and parameters have different parameter_set_id values")
    lower, upper = parameters.epsilon, 1.0 - parameters.epsilon
    if any(value < lower or value > upper for value in state.activations):
        raise EmotionValidationError("state activations are outside parameter epsilon bounds")


def _clip_impulse(raw: float, cap: float) -> float:
    finite(raw, "event impulse before clip")
    return max(-cap, min(cap, raw))


def _event_impulse(parameters: EmotionParametersV2, transition: EmotionTransitionV2) -> tuple[float, ...]:
    q = multiply(
        transition.appraisal.confidence,
        subtract(1.0, transition.appraisal.uncertainty, "event uncertainty complement"),
        "event confidence q",
    )
    result = []
    for index, (appraisal_row, memory_row) in enumerate(zip(
        parameters.w_appraisal, parameters.w_memory, strict=True,
    )):
        appraisal_dot = dot(appraisal_row, transition.appraisal.values, f"appraisal dot[{index}]")
        scaled_appraisal = multiply(q, appraisal_dot, f"scaled appraisal[{index}]")
        memory_dot = dot(memory_row, transition.memory_summary_vector, f"memory dot[{index}]")
        raw = add(scaled_appraisal, memory_dot, f"event impulse[{index}]")
        result.append(_clip_impulse(raw, parameters.event_impulse_cap))
    return tuple(result)


def _substeps(elapsed: float, parameters: EmotionParametersV2) -> tuple[int, float]:
    ratio = divide(elapsed, parameters.max_substep_seconds, "substep ratio")
    try:
        steps = max(1, math.ceil(ratio))
    except (OverflowError, ValueError) as exc:
        raise EmotionValidationError("substep count is invalid") from exc
    if steps > parameters.max_substeps_per_transition:
        raise EmotionValidationError("substep count exceeds max_substeps_per_transition")
    return steps, divide(elapsed, float(steps), "substep duration")


def reduce_emotion_v2(
    state: EmotionStateV2, parameters: EmotionParametersV2, transition: EmotionTransitionV2,
) -> EmotionStateV2:
    """Apply one explicit-time transition without I/O, clocks, or durable policy."""
    if not isinstance(state, EmotionStateV2) or not isinstance(parameters, EmotionParametersV2):
        raise EmotionValidationError("state and parameters must be Emotion V2 value objects")
    if not isinstance(transition, EmotionTransitionV2):
        raise EmotionValidationError("transition must be EmotionTransitionV2")
    _validate_state_for_parameters(state, parameters)
    if transition.is_novel_event and state.event_sequence == _SIGNED_INT64_MAX:
        raise EmotionValidationError("novel event would exceed the event_sequence signed-int64 maximum")
    if transition.elapsed_seconds == 0.0 and not transition.is_novel_event:
        return state

    y = tuple(activation_to_latent(value, parameters.epsilon) for value in state.activations)
    velocity = state.velocity
    impulse: tuple[float, ...] = ()
    if transition.is_novel_event:
        impulse = _event_impulse(parameters, transition)
        y = tuple(add(value, delta, f"event latent[{index}]") for index, (value, delta) in enumerate(zip(y, impulse, strict=True)))
        event_sequence = state.event_sequence + 1
    else:
        event_sequence = state.event_sequence

    # Avoid a gratuitous logit/sigmoid round-trip for a valid zero impulse.
    activations = (state.activations if transition.is_novel_event and not any(impulse)
                   else tuple(latent_to_activation(value, parameters.epsilon) for value in y))
    mood = state.mood
    uncertainty = state.uncertainty
    elapsed = transition.elapsed_seconds
    if elapsed:
        steps, dt = _substeps(elapsed, parameters)
        for _ in range(steps):
            raw_target = []
            for index in range(6):
                with_bias = add(parameters.baseline_bias[index], dot(
                    parameters.w_drive[index], transition.drives, f"drive dot[{index}]"
                ), f"target drive[{index}]")
                with_trait = add(with_bias, dot(
                    parameters.w_trait[index], transition.traits, f"trait dot[{index}]"
                ), f"target trait[{index}]")
                raw_target.append(subtract(with_trait, dot(
                    parameters.k[index], activations, f"K dot[{index}]"
                ), f"target raw[{index}]"))
            y_target = tuple(activation_to_latent(
                latent_to_activation(value, parameters.epsilon), parameters.epsilon
            ) for value in raw_target)
            next_y = []
            next_velocity = []
            for index in range(6):
                omega = parameters.omega[index]
                d = subtract(y[index], y_target[index], f"critical d[{index}]")
                omega_d = multiply(omega, d, f"critical omega*d[{index}]")
                velocity_term = add(velocity[index], omega_d, f"critical velocity term[{index}]")
                omega_dt = multiply(omega, dt, f"critical omega*dt[{index}]")
                decay = exp(negate(omega_dt, f"critical decay argument[{index}]"), f"critical decay[{index}]")
                y_inner = add(d, multiply(velocity_term, dt, f"critical y*dt[{index}]"), f"critical y inner[{index}]")
                next_y.append(add(y_target[index], multiply(y_inner, decay, f"critical y decay[{index}]"), f"critical y[{index}]"))
                v_inner = subtract(velocity[index], multiply(
                    multiply(omega, velocity_term, f"critical omega*velocity[{index}]"),
                    dt,
                    f"critical velocity*dt[{index}]",
                ), f"critical v inner[{index}]")
                next_velocity.append(multiply(v_inner, decay, f"critical v[{index}]"))
            y = tuple(next_y)
            velocity = tuple(next_velocity)
            activations = tuple(latent_to_activation(value, parameters.epsilon) for value in y)
            raw_mood = add(add(
                parameters.trait_mood,
                dot(parameters.w_mood_emotion, activations, "mood emotion dot"),
                "mood emotion",
            ), dot(parameters.w_mood_drive, transition.drives, "mood drive dot"), "mood raw")
            mood_target = max(-1.0, min(1.0, raw_mood))
            mood_decay = exp(negate(divide(dt, parameters.tau_mood, "mood dt/tau"), "mood decay argument"), "mood decay")
            mood = add(mood_target, multiply(subtract(mood, mood_target, "mood difference"), mood_decay, "mood decay term"), "mood update")
            uncertainty_target = transition.appraisal.uncertainty if transition.has_event else parameters.uncertainty_baseline
            uncertainty_decay = exp(negate(divide(dt, parameters.tau_uncertainty, "uncertainty dt/tau"), "uncertainty decay argument"), "uncertainty decay")
            uncertainty = add(uncertainty_target, multiply(
                subtract(uncertainty, uncertainty_target, "uncertainty difference"),
                uncertainty_decay,
                "uncertainty decay term",
            ), "uncertainty update")

    if (not all(math.isfinite(value) for value in (*activations, *velocity, mood, uncertainty))
            or any(value < parameters.epsilon or value > 1.0 - parameters.epsilon for value in activations)
            or not -1.0 <= mood <= 1.0 or not 0.0 <= uncertainty <= 1.0):
        raise EmotionValidationError("reducer produced a non-finite or unbounded state")
    return replace(
        state, activations=activations, velocity=velocity, mood=mood, uncertainty=uncertainty,
        last_update_ns=max(state.last_update_ns, transition.wall_clock_ns), event_sequence=event_sequence,
    )


def canonical_reduction_hash(
    state: EmotionStateV2, parameters: EmotionParametersV2, transition: EmotionTransitionV2,
) -> str:
    """Hash the full ordered pure-reducer request, including its clock decision."""
    return canonical_sha256({"parameters": parameters, "state": state, "transition": transition})
