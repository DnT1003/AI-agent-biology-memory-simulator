from __future__ import annotations

import math
import hashlib

import pytest

import core.emotion_v2 as public_emotion_v2
import core.emotion_v2.engine as emotion_engine
from core.emotion_v2.dynamics import dot
from core.emotion_v2.types import canonical_json_bytes

from core.emotion_v2 import (
    APPRAISAL_ORDER,
    COMPONENT_ORDER,
    DRIVE_ORDER,
    MEMORY_SUMMARY_ORDER,
    TRAIT_ORDER,
    AppraisalInputV2,
    EmotionParametersV2,
    EmotionStateV2,
    EmotionTransitionV2,
    EmotionValidationError,
    canonical_reduction_hash,
    reduce_emotion_v2,
)


def parameters(**changes: object) -> EmotionParametersV2:
    values: dict[str, object] = {
        "parameter_set_id": "b1-test-v1",
        "epsilon": 0.001,
        "omega": (1.2, 1.1, 0.9, 1.3, 0.8, 1.0),
        "max_substep_seconds": 1.0,
        "max_substeps_per_transition": 1_000,
        "baseline_bias": (0.1, -0.2, 0.3, -0.1, 0.2, 0.0),
        "w_drive": ((0.1, 0.0, 0.0, 0.0),) * 6,
        "w_trait": ((0.0, 0.0, 0.0, 0.0, 0.0),) * 6,
        "k": ((0.0, 0.0, 0.0, 0.0, 0.0, 0.0),) * 6,
        "w_appraisal": ((0.1, 0.2, 0.3, -0.1, 0.1, 0.0, 0.0, 0.0, 0.1),) * 6,
        "w_memory": ((0.1, 0.1, 0.1, 0.1),) * 6,
        "trait_mood": 0.05,
        "w_mood_emotion": (0.1, -0.1, -0.1, -0.1, 0.05, 0.1),
        "w_mood_drive": (-0.1, 0.0, 0.0, 0.0),
        "uncertainty_baseline": 0.2,
        "tau_mood": 2.0,
        "tau_uncertainty": 3.0,
        "event_impulse_cap": 0.4,
        "g_encode_max": 1.0,
    }
    values.update(changes)
    return EmotionParametersV2(**values)  # type: ignore[arg-type]


def state(**changes: object) -> EmotionStateV2:
    values: dict[str, object] = {
        "activations": (0.20, 0.35, 0.40, 0.25, 0.55, 0.45),
        "velocity": (0.0,) * 6,
        "mood": 0.1,
        "uncertainty": 0.6,
        "last_update_ns": 100,
        "event_sequence": 7,
        "parameter_set_id": "b1-test-v1",
    }
    values.update(changes)
    return EmotionStateV2(**values)  # type: ignore[arg-type]


def appraisal(confidence: float = 0.8, uncertainty: float = 0.25) -> AppraisalInputV2:
    return AppraisalInputV2((0.4, 0.2, 0.7, 0.3, 0.8, -0.2, 0.5, 0.1, 0.6), confidence, uncertainty)


def transition(**changes: object) -> EmotionTransitionV2:
    values: dict[str, object] = {
        "appraisal": appraisal(),
        "drives": (0.2, 0.3, 0.4, 0.5),
        "traits": (0.5, 1.0, 1.0, 0.7, 0.9),
        "memory_summary_vector": (0.02, 0.04, 0.06, 0.08),
        "has_event": True,
        "is_novel_event": True,
        "elapsed_seconds": 1.0,
        "wall_clock_ns": 1_000_000_100,
    }
    values.update(changes)
    return EmotionTransitionV2(**values)  # type: ignore[arg-type]


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


def _latent(activation: float, epsilon: float) -> float:
    return math.log((activation - epsilon) / (1.0 - epsilon - activation))


def _activation(latent: float, epsilon: float) -> float:
    return epsilon + (1.0 - 2.0 * epsilon) * _sigmoid(latent)


def test_fixed_component_and_input_orders_are_frozen() -> None:
    assert COMPONENT_ORDER == ("joy", "sadness", "fear", "anger", "interest", "calm")
    assert APPRAISAL_ORDER == ("valence", "goal_congruence", "novelty", "threat", "controllability", "agency_self_other", "social_relevance", "norm_conflict", "arousal")
    assert DRIVE_ORDER == ("fatigue", "energy_deficit", "social_need", "curiosity")
    assert TRAIT_ORDER == ("negative_sensitivity", "reward_sensitivity", "recovery_rate", "novelty_seeking", "affiliation")
    assert MEMORY_SUMMARY_ORDER == ("dose_weighted_valence", "dose_weighted_arousal", "dose_confidence", "dose")


@pytest.mark.parametrize("factory", [
    lambda: EmotionStateV2((0.5,) * 6, (0.0,) * 6, 0.0, 0.0, True, 0, "x"),
    lambda: AppraisalInputV2((0.0,) * 9, True, 0.0),
    lambda: transition(elapsed_seconds=True),
    lambda: parameters(epsilon=True),
])
def test_bool_is_never_a_number(factory: object) -> None:
    with pytest.raises(EmotionValidationError):
        factory()  # type: ignore[operator]


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_nonfinite_values_are_rejected(bad: float) -> None:
    with pytest.raises(EmotionValidationError):
        parameters(omega=(bad,) * 6)
    with pytest.raises(EmotionValidationError):
        EmotionStateV2((0.5,) * 6, (bad,) * 6, 0.0, 0.0, 0, 0, "x")


def test_public_appraisal_dto_rejects_oversized_integer_conversion() -> None:
    with pytest.raises(EmotionValidationError):
        AppraisalInputV2((10**10000, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0), 0.5, 0.5)


def test_persistence_bound_integer_dto_and_sequence_boundaries(monkeypatch: pytest.MonkeyPatch) -> None:
    maximum = 2**63 - 1
    maximum_state = state(last_update_ns=maximum, event_sequence=maximum)
    maximum_transition = transition(wall_clock_ns=maximum)
    assert len(maximum_state.canonical_hash()) == 64
    assert len(maximum_transition.canonical_hash()) == 64
    for factory in (
        lambda: state(last_update_ns=maximum + 1),
        lambda: state(event_sequence=maximum + 1),
        lambda: transition(wall_clock_ns=maximum + 1),
    ):
        with pytest.raises(EmotionValidationError):
            factory()
    incremented = reduce_emotion_v2(
        state(event_sequence=maximum - 1), parameters(), transition(elapsed_seconds=0.0),
    )
    assert incremented.event_sequence == maximum
    assert len(incremented.canonical_hash()) == 64
    monkeypatch.setattr(emotion_engine, "_event_impulse", lambda *_: pytest.fail("impulse must not run"))
    with pytest.raises(EmotionValidationError):
        reduce_emotion_v2(maximum_state, parameters(), maximum_transition)
    preserved = reduce_emotion_v2(
        maximum_state, parameters(), transition(is_novel_event=False, elapsed_seconds=0.0),
    )
    assert preserved is maximum_state


def test_dimensions_ranges_and_parameter_invariants_are_rejected() -> None:
    with pytest.raises(EmotionValidationError):
        transition(drives=(0.0,) * 3)
    with pytest.raises(EmotionValidationError):
        transition(memory_summary_vector=(0.0,) * 5)
    with pytest.raises(EmotionValidationError):
        AppraisalInputV2((0.0,) * 8, 0.5, 0.5)
    with pytest.raises(EmotionValidationError):
        parameters(epsilon=0.01)
    with pytest.raises(EmotionValidationError):
        parameters(omega=(0.0,) * 6)
    with pytest.raises(EmotionValidationError):
        parameters(max_substep_seconds=0.0)
    for invalid_limit in (False, 0, 10_001):
        with pytest.raises(EmotionValidationError):
            parameters(max_substeps_per_transition=invalid_limit)
    with pytest.raises(EmotionValidationError):
        parameters(k=((4.0, 0.0, 0.0, 0.0, 0.0, 0.0),) * 6)
    with pytest.raises(EmotionValidationError):
        parameters(w_memory=((16.0, 0.0, 0.0, 0.0),) * 6)
    with pytest.raises(EmotionValidationError):
        reduce_emotion_v2(state(activations=(0.0005,) * 6), parameters(), transition())


def test_substep_limit_is_explicit_bounded_and_fails_closed_before_loop() -> None:
    p = parameters(max_substep_seconds=0.1, max_substeps_per_transition=10)
    exact = reduce_emotion_v2(state(), p, transition(
        has_event=False, is_novel_event=False, elapsed_seconds=1.0,
    ))
    assert exact.event_sequence == state().event_sequence
    with pytest.raises(EmotionValidationError):
        reduce_emotion_v2(state(), p, transition(
            has_event=False, is_novel_event=False, elapsed_seconds=1.1,
        ))
    with pytest.raises(EmotionValidationError):
        reduce_emotion_v2(state(), parameters(max_substep_seconds=5e-324), transition(
            has_event=False, is_novel_event=False, elapsed_seconds=1.0,
        ))


def test_checked_finite_arithmetic_rejects_overflow_before_clipping_or_looping() -> None:
    with pytest.raises(EmotionValidationError):
        dot((1e308, 1e308, -1e308), (1.0, 1.0, 1.0), "overflow/cancellation")
    with pytest.raises(EmotionValidationError):
        reduce_emotion_v2(state(), parameters(w_appraisal=((0.0, 0.0, 1e308, 0.0, 1e308, 0.0, 1e308, 0.0, 0.0),) * 6), transition(elapsed_seconds=0.0))
    with pytest.raises(EmotionValidationError):
        reduce_emotion_v2(state(), parameters(
            trait_mood=1.7e308, w_mood_emotion=(1e308, 0.0, 0.0, 0.0, 0.0, 0.0),
        ), transition(has_event=False, is_novel_event=False, elapsed_seconds=1.0))
    with pytest.raises(EmotionValidationError):
        reduce_emotion_v2(state(velocity=(1.0,) * 6), parameters(omega=(1e308,) * 6), transition(
            has_event=False, is_novel_event=False, elapsed_seconds=1.0,
        ))


def test_state_constructor_is_strict_interior_and_reducer_pairs_epsilon_inclusively() -> None:
    for endpoint in (0.0, 1.0):
        with pytest.raises(EmotionValidationError):
            state(activations=(endpoint,) * 6)
    assert state(activations=(math.nextafter(0.0, math.inf),) * 6).activations[0] > 0.0
    p = parameters()
    exact_boundary = state(activations=(p.epsilon, 1.0 - p.epsilon, p.epsilon, 1.0 - p.epsilon, 0.5, 0.5))
    assert reduce_emotion_v2(exact_boundary, p, transition(is_novel_event=False, elapsed_seconds=0.0)) is exact_boundary
    with pytest.raises(EmotionValidationError):
        reduce_emotion_v2(state(activations=(math.nextafter(p.epsilon, 0.0),) * 6), p, transition())


def test_memory_summary_vector_enforces_dose_component_relationships() -> None:
    # These are the exact four positions: dose*valence, dose*arousal,
    # dose*confidence, dose.  Endpoint values and the all-zero summary are valid.
    assert transition(memory_summary_vector=(-0.20, 0.20, 0.20, 0.20)).memory_summary_vector == (-0.20, 0.20, 0.20, 0.20)
    assert transition(memory_summary_vector=(0.0, 0.0, 0.0, 0.0)).memory_summary_vector == (0.0, 0.0, 0.0, 0.0)
    for invalid in (
        (0.01, 0.0, 0.0, 0.0),  # non-zero component at zero dose
        (0.11, 0.10, 0.10, 0.10),  # absolute valence exceeds dose
        (0.10, 0.11, 0.10, 0.10),  # arousal exceeds dose
        (0.10, 0.10, 0.11, 0.10),  # confidence exceeds dose
    ):
        with pytest.raises(EmotionValidationError):
            transition(memory_summary_vector=invalid)


def test_initial_memory_weight_infinity_norm_has_exact_boundary() -> None:
    accepted = parameters(w_memory=((1.0, 0.0, 0.0, 0.0),) * 6)
    assert accepted.memory_infinity_norm == 1.0
    with pytest.raises(EmotionValidationError):
        parameters(w_memory=((math.nextafter(1.0, math.inf), 0.0, 0.0, 0.0),) * 6)


def test_asymmetric_event_impulse_and_critical_substep_match_independent_oracle() -> None:
    p = parameters(
        omega=(0.7, 0.8, 0.9, 1.0, 1.1, 1.2), max_substep_seconds=2.0,
        baseline_bias=(0.15, -0.20, 0.05, 0.10, -0.12, 0.08),
        w_drive=((0.2, -0.1, 0.05, 0.0), (0.0, 0.1, -0.2, 0.1), (0.3, 0.0, 0.1, -0.1), (-0.1, 0.2, 0.0, 0.1), (0.05, 0.1, 0.2, 0.0), (0.0, -0.2, 0.1, 0.2)),
        w_trait=((0.1, 0.0, 0.0, 0.0, 0.0), (0.0, 0.2, 0.0, 0.0, 0.0), (0.0, 0.0, 0.1, 0.0, 0.0), (0.0, 0.0, 0.0, 0.2, 0.0), (0.0, 0.0, 0.0, 0.0, 0.1), (0.1, 0.1, 0.0, 0.0, 0.0)),
        k=((0.20, 0.05, 0.0, 0.0, 0.0, 0.0), (0.0, 0.25, 0.03, 0.0, 0.0, 0.0), (0.0, 0.0, 0.30, 0.02, 0.0, 0.0), (0.0, 0.0, 0.0, 0.35, 0.01, 0.0), (0.04, 0.0, 0.0, 0.0, 0.15, 0.0), (0.0, 0.02, 0.0, 0.0, 0.0, 0.18)),
        w_appraisal=((0.20, -0.10, 0.30, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0), (-0.10, 0.20, 0.0, 0.10, 0.0, 0.0, 0.0, 0.0, 0.0), (0.0, 0.0, 0.20, 0.10, -0.10, 0.0, 0.0, 0.0, 0.0), (0.10, 0.0, 0.0, 0.20, 0.0, -0.10, 0.0, 0.0, 0.0), (0.0, 0.10, 0.0, 0.0, 0.20, 0.0, 0.10, 0.0, 0.0), (0.0, 0.0, 0.10, 0.0, 0.0, 0.20, 0.0, 0.10, 0.0)),
        w_memory=((0.20, 0.10, 0.0, 0.0), (0.0, 0.20, 0.10, 0.0), (0.10, 0.0, 0.20, 0.0), (0.0, 0.10, 0.0, 0.20), (0.15, 0.05, 0.0, 0.0), (0.0, 0.0, 0.05, 0.15)),
    )
    s = state(activations=(0.21, 0.32, 0.43, 0.54, 0.65, 0.46), velocity=(0.07, -0.04, 0.03, -0.02, 0.05, -0.06), mood=-0.2, uncertainty=0.9)
    t = transition(elapsed_seconds=0.4, wall_clock_ns=500, drives=(0.3, 0.2, 0.1, 0.0), traits=(0.5, 1.1, 0.7, 1.3, 0.9), memory_summary_vector=(0.04, 0.03, 0.02, 0.05))
    result = reduce_emotion_v2(s, p, t)
    q = t.appraisal.confidence * (1.0 - t.appraisal.uncertainty)
    impulses = [max(-p.event_impulse_cap, min(p.event_impulse_cap, q * sum(a * b for a, b in zip(appraisal_row, t.appraisal.values)) + sum(a * b for a, b in zip(memory_row, t.memory_summary_vector)))) for appraisal_row, memory_row in zip(p.w_appraisal, p.w_memory)]
    y0 = [_latent(value, p.epsilon) + impulse for value, impulse in zip(s.activations, impulses)]
    pre_activations = [_activation(value, p.epsilon) for value in y0]
    expected_y: list[float] = []
    expected_velocity: list[float] = []
    for index in range(6):
        raw = p.baseline_bias[index] + sum(a * b for a, b in zip(p.w_drive[index], t.drives)) + sum(a * b for a, b in zip(p.w_trait[index], t.traits)) - sum(a * b for a, b in zip(p.k[index], pre_activations))
        y_target = _latent(_activation(raw, p.epsilon), p.epsilon)
        d = y0[index] - y_target
        decay = math.exp(-p.omega[index] * 0.4)
        expected_y.append(y_target + (d + (s.velocity[index] + p.omega[index] * d) * 0.4) * decay)
        expected_velocity.append((s.velocity[index] - p.omega[index] * (s.velocity[index] + p.omega[index] * d) * 0.4) * decay)
    expected_activations = [_activation(value, p.epsilon) for value in expected_y]
    mood_target = max(-1.0, min(1.0, p.trait_mood + sum(a * b for a, b in zip(p.w_mood_emotion, expected_activations)) + sum(a * b for a, b in zip(p.w_mood_drive, t.drives))))
    expected_mood = mood_target + (s.mood - mood_target) * math.exp(-0.4 / p.tau_mood)
    expected_uncertainty = t.appraisal.uncertainty + (s.uncertainty - t.appraisal.uncertainty) * math.exp(-0.4 / p.tau_uncertainty)
    assert result.activations == pytest.approx(expected_activations, abs=1e-15)
    assert result.velocity == pytest.approx(expected_velocity, abs=1e-15)
    assert result.mood == pytest.approx(expected_mood, abs=1e-15)
    assert result.uncertainty == pytest.approx(expected_uncertainty, abs=1e-15)
    assert result.event_sequence == 8


def test_zero_time_no_novel_event_is_bit_identical_and_duplicate_is_inert() -> None:
    s = state()
    duplicate = transition(is_novel_event=False, elapsed_seconds=0.0, wall_clock_ns=1)
    result = reduce_emotion_v2(s, parameters(), duplicate)
    assert result is s
    assert result.canonical_hash() == s.canonical_hash()


def test_zero_confidence_creates_no_exogenous_appraisal_impulse() -> None:
    s = state()
    no_confidence = transition(appraisal=appraisal(0.0, 0.0), memory_summary_vector=(0.0, 0.0, 0.0, 0.0), elapsed_seconds=0.0)
    result = reduce_emotion_v2(s, parameters(), no_confidence)
    assert result.activations == s.activations
    assert result.velocity == s.velocity
    assert result.event_sequence == s.event_sequence + 1


def test_outputs_stay_finite_and_bounded_for_extreme_valid_inputs() -> None:
    p = parameters(w_appraisal=((1000.0,) * 9,) * 6, event_impulse_cap=0.01)
    result = reduce_emotion_v2(state(), p, transition(elapsed_seconds=17.0))
    assert all(math.isfinite(value) and p.epsilon <= value <= 1.0 - p.epsilon for value in result.activations)
    assert all(math.isfinite(value) for value in result.velocity)
    assert -1.0 <= result.mood <= 1.0
    assert 0.0 <= result.uncertainty <= 1.0


def test_equal_substeps_match_thirty_one_second_reductions() -> None:
    p = parameters(max_substep_seconds=1.0)
    initial = state(last_update_ns=0)
    once = reduce_emotion_v2(initial, p, transition(elapsed_seconds=30.0, wall_clock_ns=30))
    many = initial
    for second in range(1, 31):
        many = reduce_emotion_v2(many, p, transition(is_novel_event=second == 1, elapsed_seconds=1.0, wall_clock_ns=second))
    assert many.activations == pytest.approx(once.activations, abs=3e-15)
    assert many.velocity == pytest.approx(once.velocity, abs=3e-15)
    assert many.mood == pytest.approx(once.mood, abs=3e-15)
    assert many.uncertainty == pytest.approx(once.uncertainty, abs=3e-15)
    assert many.event_sequence == once.event_sequence


def test_convergence_recovery_and_clock_rollback() -> None:
    p = parameters(k=((0.0,) * 6,) * 6, baseline_bias=(0.0,) * 6, w_drive=((0.0,) * 4,) * 6, w_trait=((0.0,) * 5,) * 6, tau_mood=1.0, tau_uncertainty=1.0)
    s = state(activations=(0.9,) * 6, velocity=(0.0,) * 6, mood=0.9, uncertainty=0.9, last_update_ns=1000)
    recovered = reduce_emotion_v2(s, p, transition(has_event=False, is_novel_event=False, elapsed_seconds=40.0, wall_clock_ns=900))
    assert all(value == pytest.approx(0.5, abs=1e-10) for value in recovered.activations)
    assert recovered.mood == pytest.approx(0.005, abs=1e-10)
    assert recovered.uncertainty == pytest.approx(0.2, abs=1e-10)
    assert recovered.last_update_ns == 1000
    with pytest.raises(EmotionValidationError):
        transition(elapsed_seconds=-0.1)


def test_inputs_are_copied_immutable_and_permuted_vectors_change_fixed_order_result() -> None:
    activation_list = [0.2] * 6
    velocity_list = [0.0] * 6
    drive_list = [0.1, 0.2, 0.3, 0.4]
    s = state(activations=activation_list, velocity=velocity_list)
    t = transition(drives=drive_list)
    activation_list[0] = 0.9
    velocity_list[0] = 9.0
    drive_list[0] = 0.9
    assert s.activations[0] == 0.2 and s.velocity[0] == 0.0 and t.drives[0] == 0.1
    p = parameters(w_drive=((1.0, 2.0, 3.0, 4.0),) * 6)
    left = reduce_emotion_v2(s, p, t)
    right = reduce_emotion_v2(s, p, transition(drives=(0.4, 0.3, 0.2, 0.1)))
    assert left.activations != right.activations


def test_canonical_hashes_are_stable_for_equivalent_ordered_values() -> None:
    first = state(activations=[0.2, 0.3, 0.4, 0.5, 0.6, 0.7])
    second = state(activations=(0.2, 0.3, 0.4, 0.5, 0.6, 0.7))
    assert first.canonical_hash() == second.canonical_hash()
    assert transition().canonical_hash() == transition().canonical_hash()
    assert parameters().canonical_hash() == parameters().canonical_hash()
    assert canonical_reduction_hash(first, parameters(), transition()) == canonical_reduction_hash(second, parameters(), transition())
    assert first.canonical_hash() != state(activations=first.activations, mood=0.2).canonical_hash()


def test_asymmetric_state_hash_matches_independently_derived_sha256_digest() -> None:
    fixture = EmotionStateV2(
        (0.21, 0.32, 0.43, 0.54, 0.65, 0.46),
        (0.07, -0.04, 0.03, -0.02, 0.05, -0.06),
        -0.2, 0.9, 123456789, 17, "asymmetric-v1",
    )
    independently_framed = (
        b'{"activations":[0.21,0.32,0.43,0.54,0.65,0.46],'
        b'"event_sequence":17,"last_update_ns":123456789,"mood":-0.2,'
        b'"parameter_set_id":"asymmetric-v1","uncertainty":0.9,'
        b'"velocity":[0.07,-0.04,0.03,-0.02,0.05,-0.06]}'
    )
    expected = "c79a7968ed8ef575346aa73b34a94a3666f4e981d227aafe1bd5183d06b92d3e"
    assert hashlib.sha256(independently_framed).hexdigest() == expected
    assert fixture.canonical_hash() == expected
    assert EmotionStateV2(
        fixture.activations, fixture.velocity, -0.19, fixture.uncertainty,
        fixture.last_update_ns, fixture.event_sequence, fixture.parameter_set_id,
    ).canonical_hash() != expected


def test_canonical_mappings_are_string_keyed_and_public_surface_hides_generic_helpers() -> None:
    left = {"z": [3, {"a": 1}], "a": {"nested": True}}
    right = {"a": {"nested": True}, "z": [3, {"a": 1}]}
    assert canonical_json_bytes(left) == canonical_json_bytes(right)
    with pytest.raises(EmotionValidationError):
        canonical_json_bytes({"valid": {1: "not canonical"}})
    assert "canonical_json_bytes" not in public_emotion_v2.__all__
    assert "canonical_sha256" not in public_emotion_v2.__all__
    assert not hasattr(public_emotion_v2, "canonical_json_bytes")
    assert not hasattr(public_emotion_v2, "canonical_sha256")


def test_configured_loop_gain_matches_the_frozen_equation() -> None:
    p = parameters(g_encode_max=0.75, w_memory=(
        (0.40, -0.30, 0.0, 0.0),
        (0.10, 0.20, 0.0, 0.0),
        (0.0, 0.0, 0.0, 0.0),
        (0.0, 0.0, 0.0, 0.0),
        (0.0, 0.0, 0.0, 0.0),
        (0.0, 0.0, 0.0, 0.0),
    ))
    expected = 0.75 * 0.08 * (0.20 * 0.70)
    assert p.memory_infinity_norm == pytest.approx(0.70)
    assert p.configured_loop_gain == pytest.approx(expected)


def test_one_hundred_thousand_generated_transitions_never_escape() -> None:
    p = parameters(max_substep_seconds=0.25)
    current = state(last_update_ns=0)
    for index in range(100_000):
        current = reduce_emotion_v2(current, p, EmotionTransitionV2(
            appraisal=AppraisalInputV2(((-1.0 if index % 2 else 1.0), 0.0, (index % 10) / 10, 0.9, 0.5, 0.0, 0.2, 0.1, 0.4), (index % 11) / 10, (index % 7) / 10),
            drives=((index % 5) / 4, (index % 4) / 3, (index % 3) / 2, (index % 2)),
            traits=(0.1, 1.0, 1.5, 0.5, 2.0),
            memory_summary_vector=(0.01 if index % 3 else -0.01, 0.02, 0.03, 0.04),
            has_event=True,
            is_novel_event=index % 17 == 0,
            elapsed_seconds=0.1,
            wall_clock_ns=index + 1,
        ))
        assert all(math.isfinite(value) and p.epsilon <= value <= 1.0 - p.epsilon for value in current.activations)
        assert all(math.isfinite(value) for value in current.velocity)
        assert math.isfinite(current.mood) and math.isfinite(current.uncertainty)
