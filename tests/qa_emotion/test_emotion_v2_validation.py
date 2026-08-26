from __future__ import annotations

from dataclasses import FrozenInstanceError
import json
import math
from pathlib import Path

import pytest

import core.emotion_v2 as public_emotion_v2
from core.emotion_v2 import AppraisalInputV2, EmotionParametersV2, EmotionStateV2, EmotionTransitionV2, EmotionValidationError, canonical_reduction_hash, reduce_emotion_v2


def _strict_fixture(text: str) -> object:
    def object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate fixture key: {key}")
            result[key] = value
        return result

    def constant(token: str) -> object:
        raise ValueError(f"non-finite fixture number: {token}")

    return json.loads(text, object_pairs_hook=object_pairs, parse_constant=constant)


FIXTURE = _strict_fixture((Path(__file__).parents[1] / "fixtures" / "qa_emotion" / "emotion_v2_oracle_v1.json").read_text(encoding="utf-8"))
P = next(entry["parameters"] for entry in FIXTURE["parameter_sets"] if entry["id"] == "qa-emotion-v1")
S = next(case["state"] for case in FIXTURE["cases"] if case["id"] == "principal_asymmetric_event")
T = next(case["transition"] for case in FIXTURE["cases"] if case["id"] == "principal_asymmetric_event")


def _p(**changes: object) -> EmotionParametersV2:
    raw = dict(P); raw.update(changes); return EmotionParametersV2(**raw)


def _s(**changes: object) -> EmotionStateV2:
    raw = dict(S); raw.update(changes); return EmotionStateV2(**raw)


def _t(**changes: object) -> EmotionTransitionV2:
    raw = dict(T); raw.update(changes); raw["appraisal"] = AppraisalInputV2(**raw["appraisal"]); return EmotionTransitionV2(**raw)


NUMERIC_DTO_CASES = [
    ("parameters.epsilon", lambda value: _p(epsilon=value), True),
    ("parameters.max_substeps", lambda value: _p(max_substeps_per_transition=value), False),
    ("parameters.omega", lambda value: _p(omega=[value] * 6), True),
    ("parameters.max_substep", lambda value: _p(max_substep_seconds=value), True),
    ("parameters.baseline", lambda value: _p(baseline_bias=[value] * 6), True),
    ("parameters.w_drive", lambda value: _p(w_drive=[[value] * 4] * 6), True),
    ("parameters.w_trait", lambda value: _p(w_trait=[[value] * 5] * 6), True),
    ("parameters.k", lambda value: _p(k=[[value] * 6] * 6), True),
    ("parameters.w_appraisal", lambda value: _p(w_appraisal=[[value] * 9] * 6), True),
    ("parameters.w_memory", lambda value: _p(w_memory=[[value] * 4] * 6), True),
    ("parameters.trait_mood", lambda value: _p(trait_mood=value), True),
    ("parameters.w_mood_emotion", lambda value: _p(w_mood_emotion=[value] * 6), True),
    ("parameters.w_mood_drive", lambda value: _p(w_mood_drive=[value] * 4), True),
    ("parameters.uncertainty", lambda value: _p(uncertainty_baseline=value), True),
    ("parameters.tau_mood", lambda value: _p(tau_mood=value), True),
    ("parameters.tau_uncertainty", lambda value: _p(tau_uncertainty=value), True),
    ("parameters.impulse_cap", lambda value: _p(event_impulse_cap=value), True),
    ("parameters.g_encode", lambda value: _p(g_encode_max=value), True),
    ("state.activations", lambda value: _s(activations=[value] * 6), True),
    ("state.velocity", lambda value: _s(velocity=[value] * 6), True),
    ("state.mood", lambda value: _s(mood=value), True),
    ("state.uncertainty", lambda value: _s(uncertainty=value), True),
    ("state.last_update", lambda value: _s(last_update_ns=value), False),
    ("state.event_sequence", lambda value: _s(event_sequence=value), False),
    ("appraisal.values", lambda value: AppraisalInputV2([value] * 9, 0.5, 0.5), True),
    ("appraisal.confidence", lambda value: AppraisalInputV2([0.0] * 9, value, 0.5), True),
    ("appraisal.uncertainty", lambda value: AppraisalInputV2([0.0] * 9, 0.5, value), True),
    ("transition.drives", lambda value: _t(drives=[value] * 4), True),
    ("transition.traits", lambda value: _t(traits=[value] * 5), True),
    ("transition.memory", lambda value: _t(memory_summary_vector=[value] * 4), True),
    ("transition.elapsed", lambda value: _t(elapsed_seconds=value), True),
    ("transition.wall_clock", lambda value: _t(wall_clock_ns=value), False),
]
ALL_NUMERIC_DTO_FACTORIES = [pytest.param(factory, id=name) for name, factory, _ in NUMERIC_DTO_CASES]
CONVERTED_NUMERIC_DTO_FACTORIES = [
    pytest.param(factory, id=name) for name, factory, converts in NUMERIC_DTO_CASES if converts
]


@pytest.mark.parametrize("factory", [
    lambda: _s(activations=[0.5] * 5), lambda: _s(velocity=[0.0] * 5),
    lambda: AppraisalInputV2([0.0] * 8, .5, .5), lambda: _t(drives=[0.0] * 3),
    lambda: _t(traits=[1.0] * 4), lambda: _t(memory_summary_vector=[0.0] * 3),
    lambda: _p(omega=[1.0] * 5), lambda: _p(w_drive=[[0.0] * 4] * 5),
    lambda: _p(w_trait=[[0.0] * 5] * 5), lambda: _p(k=[[0.0] * 6] * 5),
    lambda: _p(w_appraisal=[[0.0] * 9] * 5), lambda: _p(w_memory=[[0.0] * 4] * 5),
    lambda: _p(w_drive=[[0.0] * 3] * 6), lambda: _p(w_trait=[[0.0] * 4] * 6),
    lambda: _p(k=[[0.0] * 5] * 6), lambda: _p(w_appraisal=[[0.0] * 8] * 6),
    lambda: _p(w_memory=[[0.0] * 3] * 6),
])
def test_every_required_dimension_fails_closed(factory) -> None:
    with pytest.raises(EmotionValidationError): factory()


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf], ids=["nan", "positive_infinity", "negative_infinity"])
@pytest.mark.parametrize("factory", ALL_NUMERIC_DTO_FACTORIES)
def test_public_dtos_reject_every_nonfinite_numeric_family(factory, bad: float) -> None:
    with pytest.raises(EmotionValidationError):
        factory(bad)


@pytest.mark.parametrize("factory", CONVERTED_NUMERIC_DTO_FACTORIES)
def test_huge_integer_rejection_preserves_numeric_conversion_cause(factory) -> None:
    with pytest.raises(EmotionValidationError) as captured:
        factory(10**10000)
    assert type(captured.value.__cause__) is OverflowError


@pytest.mark.parametrize("factory", [
    lambda: AppraisalInputV2([-1.0, -1.0, 0.0, 0.0, 0.0, -1.0, 0.0, 0.0, 0.0], 0.0, 0.0),
    lambda: AppraisalInputV2([1.0] * 9, 1.0, 1.0),
    lambda: _t(drives=[0.0, 1.0, 0.0, 1.0]),
    lambda: _t(traits=[0.0, 2.0, 0.0, 2.0, 0.0]),
    lambda: _p(uncertainty_baseline=0.0),
    lambda: _p(uncertainty_baseline=1.0),
    lambda: _p(g_encode_max=0.0),
    lambda: _p(g_encode_max=1.0),
])
def test_all_documented_inclusive_range_endpoints_are_accepted(factory) -> None:
    factory()


@pytest.mark.parametrize("factory", [
    lambda: AppraisalInputV2([math.nextafter(-1.0, -math.inf)] + [0.0] * 8, 0.5, 0.5),
    lambda: AppraisalInputV2([0.0, 0.0, math.nextafter(1.0, math.inf)] + [0.0] * 6, 0.5, 0.5),
    lambda: AppraisalInputV2([0.0] * 9, math.nextafter(1.0, math.inf), 0.5),
    lambda: AppraisalInputV2([0.0] * 9, 0.5, math.nextafter(0.0, -math.inf)),
    lambda: _t(drives=[math.nextafter(0.0, -math.inf)] + [0.0] * 3),
    lambda: _t(traits=[math.nextafter(2.0, math.inf)] + [0.0] * 4),
    lambda: _p(uncertainty_baseline=math.nextafter(1.0, math.inf)),
    lambda: _p(g_encode_max=math.nextafter(0.0, -math.inf)),
])
def test_every_documented_range_rejects_one_ulp_outside(factory) -> None:
    with pytest.raises(EmotionValidationError):
        factory()


@pytest.mark.parametrize("value", [False, -1, 2**63, 10**10000], ids=["bool", "negative", "one_over", "huge"])
@pytest.mark.parametrize("field", ["last_update_ns", "event_sequence"])
def test_all_state_int64_fields_reject_boolean_negative_one_over_and_huge(field: str, value: object) -> None:
    with pytest.raises(EmotionValidationError): _s(**{field: value})
    with pytest.raises(EmotionValidationError): _t(wall_clock_ns=value)


def test_int64_sequence_ordering_maximum_replay_and_rollback() -> None:
    maximum = 2**63 - 1
    p, state = _p(), _s(event_sequence=maximum - 1, last_update_ns=maximum)
    incremented = reduce_emotion_v2(state, p, _t(elapsed_seconds=0.0, wall_clock_ns=maximum))
    assert incremented.event_sequence == maximum
    assert reduce_emotion_v2(incremented, p, _t(is_novel_event=False, elapsed_seconds=0.0, wall_clock_ns=0)) is incremented
    with pytest.raises(EmotionValidationError): reduce_emotion_v2(incremented, p, _t(elapsed_seconds=0.0))
    assert reduce_emotion_v2(_s(last_update_ns=99), p, _t(is_novel_event=False, has_event=False, elapsed_seconds=.125, wall_clock_ns=1)).last_update_ns == 99


def test_endpoints_epsilon_pairing_memory_and_parameter_boundaries() -> None:
    p = _p()
    upper_epsilon = math.nextafter(0.01, 0.0)
    assert _p(epsilon=upper_epsilon).epsilon == upper_epsilon
    for invalid_epsilon in (0.0, 0.01):
        with pytest.raises(EmotionValidationError): _p(epsilon=invalid_epsilon)
    for field in ("omega",):
        assert _p(**{field: [5e-324] * 6}).omega[0] == 5e-324
        with pytest.raises(EmotionValidationError): _p(**{field: [0.0] * 6})
    assert _p(max_substep_seconds=5e-324).max_substep_seconds == 5e-324
    with pytest.raises(EmotionValidationError): _p(max_substep_seconds=0.0)
    for field in ("tau_mood", "tau_uncertainty", "event_impulse_cap"):
        assert getattr(_p(**{field: 5e-324}), field) == 5e-324
        with pytest.raises(EmotionValidationError): _p(**{field: 0.0})
    assert _s(mood=-1.0, uncertainty=0.0).mood == -1.0
    assert _s(mood=1.0, uncertainty=1.0).uncertainty == 1.0
    with pytest.raises(EmotionValidationError): _s(mood=math.nextafter(-1.0, -math.inf))
    with pytest.raises(EmotionValidationError): _s(uncertainty=math.nextafter(1.0, math.inf))
    for endpoint in (0.0, 1.0):
        with pytest.raises(EmotionValidationError): _s(activations=[endpoint] * 6)
    paired = reduce_emotion_v2(_s(activations=[p.epsilon, 1.0 - p.epsilon, .5, .5, .5, .5]), p, _t(is_novel_event=False, elapsed_seconds=0.0))
    assert paired.activations[:2] == (p.epsilon, 1.0 - p.epsilon)
    with pytest.raises(EmotionValidationError): reduce_emotion_v2(_s(activations=[math.nextafter(p.epsilon, 0.0)] * 6), p, _t())
    with pytest.raises(EmotionValidationError): reduce_emotion_v2(_s(activations=[math.nextafter(1.0 - p.epsilon, math.inf)] * 6), p, _t())
    assert _t(memory_summary_vector=[0.0, 0.0, 0.0, 0.0]).memory_summary_vector == (0.0, 0.0, 0.0, 0.0)
    for index, equal in ((0, 0.2), (0, -0.2), (1, 0.2), (2, 0.2)):
        vector = [0.0, 0.0, 0.0, 0.2]
        vector[index] = equal
        assert _t(memory_summary_vector=vector).memory_summary_vector[index] == equal
        vector[index] = math.copysign(math.nextafter(0.2, math.inf), equal)
        with pytest.raises(EmotionValidationError): _t(memory_summary_vector=vector)
    for index, value in ((0, 5e-324), (0, -5e-324), (1, 5e-324), (2, 5e-324)):
        vector = [0.0, 0.0, 0.0, 0.0]
        vector[index] = value
        with pytest.raises(EmotionValidationError): _t(memory_summary_vector=vector)
    assert _p(w_memory=[[1.0, 0.0, 0.0, 0.0]] * 6).memory_infinity_norm == 1.0
    with pytest.raises(EmotionValidationError): _p(w_memory=[[math.nextafter(1.0, math.inf), 0.0, 0.0, 0.0]] * 6)
    below_four = math.nextafter(4.0, 0.0)
    assert _p(k=[[below_four, 0.0, 0.0, 0.0, 0.0, 0.0]] * 6).k[0][0] == below_four
    with pytest.raises(EmotionValidationError): _p(k=[[4.0, 0.0, 0.0, 0.0, 0.0, 0.0]] * 6)


def test_substep_limits_nonfinite_arithmetic_and_tau_parity() -> None:
    assert _p(max_substeps_per_transition=1).max_substeps_per_transition == 1
    assert _p(max_substeps_per_transition=10_000).max_substeps_per_transition == 10_000
    for bad in (False, 0, 10_001):
        with pytest.raises(EmotionValidationError): _p(max_substeps_per_transition=bad)
    with pytest.raises(EmotionValidationError): _p(max_substeps_per_transition=10**10000)
    p = _p(max_substep_seconds=.1, max_substeps_per_transition=2)
    exact = reduce_emotion_v2(_s(), p, _t(is_novel_event=False, has_event=False, elapsed_seconds=.2))
    assert exact.event_sequence == S["event_sequence"]
    with pytest.raises(EmotionValidationError): reduce_emotion_v2(_s(), p, _t(is_novel_event=False, has_event=False, elapsed_seconds=math.nextafter(.2, math.inf)))
    with pytest.raises(EmotionValidationError):
        reduce_emotion_v2(_s(), _p(max_substep_seconds=5e-324), _t(is_novel_event=False, has_event=False, elapsed_seconds=1.0))
    for kwargs in ({"w_appraisal": [[1e308] * 9] * 6}, {"trait_mood": 1.7e308, "w_mood_emotion": [1e308, 0, 0, 0, 0, 0]}, {"omega": [1e308] * 6}, {"tau_mood": 5e-324}, {"tau_uncertainty": 5e-324}):
        transition = _t(elapsed_seconds=1.0) if "w_appraisal" in kwargs else _t(is_novel_event=False, has_event=False, elapsed_seconds=1.0)
        with pytest.raises(EmotionValidationError): reduce_emotion_v2(_s(), _p(**kwargs), transition)


def test_checked_arithmetic_failures_are_observable_only_through_the_public_reducer() -> None:
    with pytest.raises(EmotionValidationError):
        reduce_emotion_v2(_s(), _p(baseline_bias=[1.7e308] * 6, w_drive=[[1e308, 0.0, 0.0, 0.0]] * 6), _t(is_novel_event=False, has_event=False, elapsed_seconds=0.5))
    with pytest.raises(EmotionValidationError):
        reduce_emotion_v2(_s(velocity=[1.0] * 6), _p(omega=[1e308] * 6), _t(is_novel_event=False, has_event=False, elapsed_seconds=1.0))
    with pytest.raises(EmotionValidationError):
        reduce_emotion_v2(_s(), _p(trait_mood=1.7e308, w_mood_emotion=[1e308, 0.0, 0.0, 0.0, 0.0, 0.0]), _t(is_novel_event=False, has_event=False, elapsed_seconds=1.0))


def test_overflow_and_validation_precedence_use_only_exported_public_paths() -> None:
    overflowing_parameters = _p(w_appraisal=[[1e308] * 9] * 6)
    overflowing_transition = _t(appraisal={
        "values": [1.0] * 9, "confidence": 1.0, "uncertainty": 0.0,
    }, memory_summary_vector=[0.0] * 4, elapsed_seconds=0.0)
    with pytest.raises(EmotionValidationError):
        reduce_emotion_v2(_s(), overflowing_parameters, overflowing_transition)
    with pytest.raises(EmotionValidationError, match="event_sequence"):
        reduce_emotion_v2(_s(event_sequence=2**63 - 1), overflowing_parameters, overflowing_transition)
    with pytest.raises(EmotionValidationError, match="different parameter_set_id"):
        reduce_emotion_v2(
            _s(parameter_set_id="mismatched-v1", event_sequence=2**63 - 1),
            overflowing_parameters,
            overflowing_transition,
        )


def test_finite_large_mood_target_clips_before_bounded_public_update() -> None:
    parameters = _p(
        trait_mood=1e308,
        w_mood_emotion=[0.0] * 6,
        w_mood_drive=[0.0] * 4,
    )
    transition = _t(is_novel_event=False, has_event=False, elapsed_seconds=0.8)
    result = reduce_emotion_v2(_s(), parameters, transition)
    expected = 1.0 + (S["mood"] - 1.0) * math.exp(-0.8 / parameters.tau_mood)
    assert math.isfinite(result.mood)
    assert result.mood == pytest.approx(expected, abs=1e-15)
    assert -1.0 <= result.mood <= 1.0


def test_parameter_and_request_hashes_are_sensitive_to_max_substeps() -> None:
    low = _p(max_substeps_per_transition=63)
    high = _p(max_substeps_per_transition=64)
    state, transition = _s(), _t()
    assert low.canonical_hash() != high.canonical_hash()
    assert canonical_reduction_hash(state, low, transition) != canonical_reduction_hash(state, high, transition)


def test_public_surface_is_exact() -> None:
    assert public_emotion_v2.__all__ == [
        "APPRAISAL_ORDER", "COMPONENT_ORDER", "DRIVE_ORDER", "MEMORY_SUMMARY_ORDER", "TRAIT_ORDER",
        "AppraisalInputV2", "EmotionParametersV2", "EmotionStateV2", "EmotionTransitionV2",
        "EmotionValidationError", "canonical_reduction_hash", "reduce_emotion_v2",
    ]


def test_input_detachment_including_nested_rows_and_transition_vectors() -> None:
    activations, velocity = list(S["activations"]), list(S["velocity"])
    appraisal_values = list(T["appraisal"]["values"])
    appraisal_raw = {**T["appraisal"], "values": appraisal_values}
    parameter_vectors = {field: list(P[field]) for field in ("omega", "baseline_bias", "w_mood_emotion", "w_mood_drive")}
    parameter_matrices = {field: [list(row) for row in P[field]] for field in ("w_drive", "w_trait", "k", "w_appraisal", "w_memory")}
    drives, traits, memory = list(T["drives"]), list(T["traits"]), list(T["memory_summary_vector"])
    state = _s(activations=activations, velocity=velocity)
    appraisal = AppraisalInputV2(**appraisal_raw)
    parameters = _p(**parameter_vectors, **parameter_matrices)
    transition = _t(appraisal=appraisal_raw, drives=drives, traits=traits, memory_summary_vector=memory)
    activations[0] = velocity[0] = appraisal_values[0] = 99.0
    for value in parameter_vectors.values(): value[0] = 99.0
    for value in parameter_matrices.values(): value[0][0] = 99.0
    drives[0] = .99; traits[0] = 0.0; memory[0] = 0.0
    assert state.activations[0] == .18 and state.velocity[0] == .09 and appraisal.values[0] == .37
    assert parameters.omega[0] == .65 and parameters.w_drive[0][0] == .16
    assert parameters.w_trait[0][0] == .08 and parameters.k[0][0] == .22
    assert parameters.w_appraisal[0][0] == .31 and parameters.w_memory[0][0] == .3
    assert transition.drives[0] == .27 and transition.traits[0] == .6 and transition.memory_summary_vector[0] == -.06
    with pytest.raises((FrozenInstanceError, AttributeError)): transition.has_event = False  # type: ignore[misc]
