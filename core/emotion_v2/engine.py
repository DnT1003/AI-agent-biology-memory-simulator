"""The bounded deterministic Emotion V2 control reducer."""

from __future__ import annotations

from dataclasses import replace
import math

from .dynamics import activation_to_latent, dot, latent_to_activation
from .parameters import EmotionParametersV2
from .types import EmotionStateV2, EmotionTransitionV2, EmotionValidationError, canonical_sha256


def _validate_state_for_parameters(state: EmotionStateV2, parameters: EmotionParametersV2) -> None:
    if state.parameter_set_id != parameters.parameter_set_id:
        raise EmotionValidationError("state and parameters have different parameter_set_id values")
    lower, upper = parameters.epsilon, 1.0 - parameters.epsilon
    if any(value < lower or value > upper for value in state.activations):
        raise EmotionValidationError("state activations are outside parameter epsilon bounds")


def _event_impulse(parameters: EmotionParametersV2, transition: EmotionTransitionV2) -> tuple[float, ...]:
    q = transition.appraisal.confidence * (1.0 - transition.appraisal.uncertainty)
    result = []
    for appraisal_row, memory_row in zip(parameters.w_appraisal, parameters.w_memory, strict=True):
        raw = q * dot(appraisal_row, transition.appraisal.values) + dot(memory_row, transition.memory_summary_vector)
        result.append(max(-parameters.event_impulse_cap, min(parameters.event_impulse_cap, raw)))
    return tuple(result)


def reduce_emotion_v2(
    state: EmotionStateV2, parameters: EmotionParametersV2, transition: EmotionTransitionV2,
) -> EmotionStateV2:
    """Apply one explicit-time transition without I/O, clocks, or durable policy."""
    if not isinstance(state, EmotionStateV2) or not isinstance(parameters, EmotionParametersV2):
        raise EmotionValidationError("state and parameters must be Emotion V2 value objects")
    if not isinstance(transition, EmotionTransitionV2):
        raise EmotionValidationError("transition must be EmotionTransitionV2")
    _validate_state_for_parameters(state, parameters)
    if transition.elapsed_seconds == 0.0 and not transition.is_novel_event:
        return state

    y = tuple(activation_to_latent(value, parameters.epsilon) for value in state.activations)
    velocity = state.velocity
    if transition.is_novel_event:
        impulse = _event_impulse(parameters, transition)
        y = tuple(value + delta for value, delta in zip(y, impulse, strict=True))
        event_sequence = state.event_sequence + 1
    else:
        event_sequence = state.event_sequence

    # Avoid a gratuitous logit/sigmoid round-trip for a valid zero impulse.
    # This keeps a zero-time, zero-confidence novel event exact apart from its
    # explicitly incremented event sequence.
    activations = (state.activations if transition.is_novel_event and not any(impulse)
                   else tuple(latent_to_activation(value, parameters.epsilon) for value in y))
    mood = state.mood
    uncertainty = state.uncertainty
    elapsed = transition.elapsed_seconds
    if elapsed:
        steps = max(1, math.ceil(elapsed / parameters.max_substep_seconds))
        dt = elapsed / steps
        for _ in range(steps):
            raw_target = tuple(
                parameters.baseline_bias[index]
                + dot(parameters.w_drive[index], transition.drives)
                + dot(parameters.w_trait[index], transition.traits)
                - dot(parameters.k[index], activations)
                for index in range(6)
            )
            y_target = tuple(activation_to_latent(
                latent_to_activation(value, parameters.epsilon), parameters.epsilon
            ) for value in raw_target)
            next_y = []
            next_velocity = []
            for index in range(6):
                omega = parameters.omega[index]
                d = y[index] - y_target[index]
                decay = math.exp(-omega * dt)
                next_y.append(y_target[index] + (d + (velocity[index] + omega * d) * dt) * decay)
                next_velocity.append((velocity[index] - omega * (velocity[index] + omega * d) * dt) * decay)
            y = tuple(next_y)
            velocity = tuple(next_velocity)
            activations = tuple(latent_to_activation(value, parameters.epsilon) for value in y)
            mood_target = max(-1.0, min(1.0, parameters.trait_mood
                + dot(parameters.w_mood_emotion, activations)
                + dot(parameters.w_mood_drive, transition.drives)))
            mood = mood_target + (mood - mood_target) * math.exp(-dt / parameters.tau_mood)
            uncertainty_target = transition.appraisal.uncertainty if transition.has_event else parameters.uncertainty_baseline
            uncertainty = uncertainty_target + (uncertainty - uncertainty_target) * math.exp(-dt / parameters.tau_uncertainty)

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
