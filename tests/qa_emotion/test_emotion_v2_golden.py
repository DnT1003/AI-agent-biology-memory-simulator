from __future__ import annotations

import copy
from dataclasses import asdict
import importlib.util
from pathlib import Path
import sys

import pytest

from core.emotion_v2 import (
    APPRAISAL_ORDER, COMPONENT_ORDER, DRIVE_ORDER, MEMORY_SUMMARY_ORDER, TRAIT_ORDER,
    AppraisalInputV2, EmotionParametersV2, EmotionStateV2, EmotionTransitionV2, EmotionValidationError,
    canonical_reduction_hash, reduce_emotion_v2,
)


def _load_reference_module():
    module_name = "_aura_q5_emotion_reference_v1"
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing
    reference_path = Path(__file__).resolve().parents[1] / "reference" / "emotion_model.py"
    if not reference_path.is_file():
        raise RuntimeError(f"missing Q5 reference module: {reference_path}")
    spec = importlib.util.spec_from_file_location(module_name, reference_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot construct Q5 reference-module spec")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    return module


REFERENCE = _load_reference_module()
ROOT = Path(__file__).parents[1]
FIXTURE_PATH = ROOT / "fixtures" / "qa_emotion" / "emotion_v2_oracle_v1.json"
FIXTURE = REFERENCE.strict_json_loads(FIXTURE_PATH.read_text(encoding="utf-8"))
PARAMETERS = {entry["id"]: entry for entry in FIXTURE["parameter_sets"]}

PARAMETER_KEYS = {
    "parameter_set_id", "epsilon", "omega", "max_substep_seconds",
    "max_substeps_per_transition", "baseline_bias", "w_drive", "w_trait", "k",
    "w_appraisal", "w_memory", "trait_mood", "w_mood_emotion", "w_mood_drive",
    "uncertainty_baseline", "tau_mood", "tau_uncertainty", "event_impulse_cap",
    "g_encode_max",
}
STATE_KEYS = {
    "activations", "velocity", "mood", "uncertainty", "last_update_ns",
    "event_sequence", "parameter_set_id",
}
TRANSITION_KEYS = {
    "appraisal", "drives", "traits", "memory_summary_vector", "has_event",
    "is_novel_event", "elapsed_seconds", "wall_clock_ns",
}
GENERATOR_KEYS = {
    "formula_id", "index_origin", "valence_cycle", "goal_congruence_cycle",
    "agency_cycle", "confidence_cycle", "uncertainty_cycle", "dose_cycle",
    "memory_valence_cycle", "memory_arousal_cycle", "memory_confidence_cycle",
    "traits", "novel_modulus", "event_absence_modulus", "elapsed_seconds",
    "clock_step_ns",
}


def _state(raw: dict[str, object]) -> EmotionStateV2:
    return EmotionStateV2(**raw)


def _parameters(raw: dict[str, object]) -> EmotionParametersV2:
    return EmotionParametersV2(**raw)


def _transition(raw: dict[str, object]) -> EmotionTransitionV2:
    value = dict(raw)
    value["appraisal"] = AppraisalInputV2(**value["appraisal"])
    return EmotionTransitionV2(**value)


def _closed(value: object, keys: set[str]) -> None:
    assert type(value) is dict
    assert set(value) == keys


def _kind(value: object, expected: type, label: str) -> None:
    assert type(value) is expected, f"{label} must be an exact {expected.__name__}"


def _float_vector(value: object, length: int, label: str) -> None:
    _kind(value, list, label)
    assert len(value) == length, f"{label} length"
    for index, item in enumerate(value):
        _kind(item, float, f"{label}[{index}]")


def _float_matrix(value: object, rows: int, columns: int, label: str) -> None:
    _kind(value, list, label)
    assert len(value) == rows, f"{label} rows"
    for index, row in enumerate(value):
        _float_vector(row, columns, f"{label}[{index}]")


def _state_schema(value: object, label: str) -> None:
    _closed(value, STATE_KEYS)
    _float_vector(value["activations"], 6, f"{label}.activations")
    _float_vector(value["velocity"], 6, f"{label}.velocity")
    for field in ("mood", "uncertainty"):
        _kind(value[field], float, f"{label}.{field}")
    for field in ("last_update_ns", "event_sequence"):
        _kind(value[field], int, f"{label}.{field}")
    _kind(value["parameter_set_id"], str, f"{label}.parameter_set_id")
    assert value["parameter_set_id"]


def _transition_schema(value: object, label: str) -> None:
    _closed(value, TRANSITION_KEYS)
    _closed(value["appraisal"], {"values", "confidence", "uncertainty"})
    _float_vector(value["appraisal"]["values"], 9, f"{label}.appraisal.values")
    for field in ("confidence", "uncertainty"):
        _kind(value["appraisal"][field], float, f"{label}.appraisal.{field}")
    _float_vector(value["drives"], 4, f"{label}.drives")
    _float_vector(value["traits"], 5, f"{label}.traits")
    _float_vector(value["memory_summary_vector"], 4, f"{label}.memory_summary_vector")
    for field in ("has_event", "is_novel_event"):
        _kind(value[field], bool, f"{label}.{field}")
    _kind(value["elapsed_seconds"], float, f"{label}.elapsed_seconds")
    _kind(value["wall_clock_ns"], int, f"{label}.wall_clock_ns")


def _parameters_schema(value: object, label: str) -> None:
    _closed(value, PARAMETER_KEYS)
    _kind(value["parameter_set_id"], str, f"{label}.parameter_set_id")
    assert value["parameter_set_id"]
    for field in (
        "epsilon", "max_substep_seconds", "trait_mood", "uncertainty_baseline",
        "tau_mood", "tau_uncertainty", "event_impulse_cap", "g_encode_max",
    ):
        _kind(value[field], float, f"{label}.{field}")
    _kind(value["max_substeps_per_transition"], int, f"{label}.max_substeps_per_transition")
    for field, length in (("omega", 6), ("baseline_bias", 6), ("w_mood_emotion", 6), ("w_mood_drive", 4)):
        _float_vector(value[field], length, f"{label}.{field}")
    for field, rows, columns in (
        ("w_drive", 6, 4), ("w_trait", 6, 5), ("k", 6, 6),
        ("w_appraisal", 6, 9), ("w_memory", 6, 4),
    ):
        _float_matrix(value[field], rows, columns, f"{label}.{field}")


def _validate_fixture_schema(fixture: object) -> None:
    _closed(fixture, {"schema_version", "numeric_profile", "orders", "parameter_sets", "cases", "long_horizon"})
    _kind(fixture["schema_version"], str, "schema_version")
    _kind(fixture["numeric_profile"], str, "numeric_profile")
    _closed(fixture["orders"], {"components", "appraisal", "drives", "traits", "memory"})
    for field in ("components", "appraisal", "drives", "traits", "memory"):
        _kind(fixture["orders"][field], list, f"orders.{field}")
        assert all(type(item) is str for item in fixture["orders"][field])
    _kind(fixture["parameter_sets"], list, "parameter_sets")
    for index, entry in enumerate(fixture["parameter_sets"]):
        _closed(entry, {"id", "parameters", "expected"})
        _kind(entry["id"], str, f"parameter_sets[{index}].id")
        assert entry["id"]
        _parameters_schema(entry["parameters"], f"parameter_sets[{index}].parameters")
        assert entry["parameters"]["parameter_set_id"]
        _closed(entry["expected"], {"canonical_sha256", "memory_infinity_norm", "configured_loop_gain"})
        _kind(entry["expected"]["canonical_sha256"], str, "parameter canonical_sha256")
        _kind(entry["expected"]["memory_infinity_norm"], float, "memory_infinity_norm")
        _kind(entry["expected"]["configured_loop_gain"], float, "configured_loop_gain")
    _kind(fixture["cases"], list, "cases")
    for index, case in enumerate(fixture["cases"]):
        _closed(case, {"id", "parameter_set_id", "state", "transition", "expected"})
        _kind(case["id"], str, f"cases[{index}].id")
        _kind(case["parameter_set_id"], str, f"cases[{index}].parameter_set_id")
        assert case["id"] and case["parameter_set_id"]
        _state_schema(case["state"], f"cases[{index}].state")
        _transition_schema(case["transition"], f"cases[{index}].transition")
        expected = case["expected"]
        _closed(expected, {
            "outcome", "substeps", "reference_event_impulse", "reference_state",
            "reference_state_sha256", "public_state", "public_state_sha256",
            "transition_sha256", "request_sha256",
        })
        assert expected["outcome"] == "state"
        _kind(expected["substeps"], int, f"cases[{index}].expected.substeps")
        if expected["reference_event_impulse"] is not None:
            _float_vector(expected["reference_event_impulse"], 6, f"cases[{index}].expected.reference_event_impulse")
        _state_schema(expected["reference_state"], f"cases[{index}].expected.reference_state")
        _state_schema(expected["public_state"], f"cases[{index}].expected.public_state")
        for field in ("reference_state_sha256", "public_state_sha256", "transition_sha256", "request_sha256"):
            _kind(expected[field], str, f"cases[{index}].expected.{field}")
    horizon = fixture["long_horizon"]
    _closed(horizon, {"id", "parameter_set_id", "initial_state", "steps", "generator", "expected"})
    for field in ("id", "parameter_set_id"):
        _kind(horizon[field], str, f"long_horizon.{field}")
        assert horizon[field]
    _kind(horizon["steps"], int, "long_horizon.steps")
    _state_schema(horizon["initial_state"], "long_horizon.initial_state")
    generator = horizon["generator"]
    _closed(generator, GENERATOR_KEYS)
    _kind(generator["formula_id"], str, "generator.formula_id")
    for field in ("index_origin", "novel_modulus", "event_absence_modulus", "clock_step_ns"):
        _kind(generator[field], int, f"generator.{field}")
    _kind(generator["elapsed_seconds"], float, "generator.elapsed_seconds")
    for field, length in (
        ("valence_cycle", 5), ("goal_congruence_cycle", 4), ("agency_cycle", 5),
        ("confidence_cycle", 4), ("uncertainty_cycle", 5), ("dose_cycle", 4),
        ("memory_valence_cycle", 4), ("memory_arousal_cycle", 4),
        ("memory_confidence_cycle", 4), ("traits", 5),
    ):
        _float_vector(generator[field], length, f"generator.{field}")
    expected = horizon["expected"]
    _closed(expected, {
        "reference_checkpoint_sha256", "public_checkpoint_sha256",
        "reference_final_state", "public_final_state", "reference_final_sha256",
        "public_final_sha256", "metrics",
    })
    for field in ("reference_checkpoint_sha256", "public_checkpoint_sha256"):
        _closed(expected[field], {"1", "16", "256", "1024", "4096"})
        assert all(type(value) is str for value in expected[field].values())
    _state_schema(expected["reference_final_state"], "long_horizon.expected.reference_final_state")
    _state_schema(expected["public_final_state"], "long_horizon.expected.public_final_state")
    _kind(expected["reference_final_sha256"], str, "long_horizon.expected.reference_final_sha256")
    _kind(expected["public_final_sha256"], str, "long_horizon.expected.public_final_sha256")
    metrics = expected["metrics"]
    _closed(metrics, {"activation_total_variation", "mean_activation", "mean_mood", "mean_uncertainty", "peak_abs_velocity", "saturation_fraction"})
    _float_vector(metrics["mean_activation"], 6, "metrics.mean_activation")
    _float_vector(metrics["peak_abs_velocity"], 6, "metrics.peak_abs_velocity")
    for field in ("activation_total_variation", "mean_mood", "mean_uncertainty", "saturation_fraction"):
        _kind(metrics[field], float, f"metrics.{field}")


def test_fixture_schema_is_strict_closed_and_uses_adjudicated_orders() -> None:
    _validate_fixture_schema(FIXTURE)
    assert FIXTURE["schema_version"] == "emotion-v2-qa-oracle/1"
    assert FIXTURE["numeric_profile"] == "cpython-3.12-binary64-sequential-v1"
    assert tuple(FIXTURE["orders"]["components"]) == COMPONENT_ORDER
    assert tuple(FIXTURE["orders"]["appraisal"]) == APPRAISAL_ORDER
    assert tuple(FIXTURE["orders"]["drives"]) == DRIVE_ORDER
    assert tuple(FIXTURE["orders"]["traits"]) == TRAIT_ORDER
    assert tuple(FIXTURE["orders"]["memory"]) == MEMORY_SUMMARY_ORDER


def test_fixture_schema_rejects_superseded_single_profile_aliases() -> None:
    old_case = copy.deepcopy(FIXTURE)
    case_expected = old_case["cases"][0]["expected"]
    state = case_expected.pop("reference_state")
    digest = case_expected.pop("reference_state_sha256")
    impulse = case_expected.pop("reference_event_impulse")
    case_expected.pop("public_state")
    case_expected.pop("public_state_sha256")
    case_expected.update({"event_impulse": impulse, "state": state, "state_sha256": digest})
    with pytest.raises(AssertionError):
        _validate_fixture_schema(old_case)

    old_horizon = copy.deepcopy(FIXTURE)
    horizon_expected = old_horizon["long_horizon"]["expected"]
    checkpoints = horizon_expected.pop("reference_checkpoint_sha256")
    final_state = horizon_expected.pop("reference_final_state")
    final_digest = horizon_expected.pop("reference_final_sha256")
    horizon_expected.pop("public_checkpoint_sha256")
    horizon_expected.pop("public_final_state")
    horizon_expected.pop("public_final_sha256")
    horizon_expected.update({
        "checkpoint_sha256": checkpoints,
        "final_state": final_state,
        "final_sha256": final_digest,
    })
    with pytest.raises(AssertionError):
        _validate_fixture_schema(old_horizon)


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_strict_fixture_loader_rejects_bare_nonfinite_constants(constant: str) -> None:
    with pytest.raises(REFERENCE.ReferenceContractError):
        REFERENCE.strict_json_loads('{"outer":{"value":' + constant + "}}")


@pytest.mark.parametrize("source", [
    '{"duplicate":1,"duplicate":2}',
    '{"outer":{"duplicate":1,"duplicate":2}}',
    '{"items":[{"duplicate":1,"duplicate":2}]}',
])
def test_strict_fixture_loader_rejects_duplicate_keys_at_every_depth(source: str) -> None:
    with pytest.raises(REFERENCE.ReferenceContractError):
        REFERENCE.strict_json_loads(source)


def test_parameter_hash_gain_and_memory_norm_are_static_literals() -> None:
    for entry in FIXTURE["parameter_sets"]:
        raw, expected = entry["parameters"], entry["expected"]
        public = _parameters(raw)
        assert REFERENCE.canonical_digest(REFERENCE.normalize_parameters(raw)) == expected["canonical_sha256"]
        assert public.canonical_hash() == expected["canonical_sha256"]
        assert REFERENCE.configured_loop_gain(raw) == expected["configured_loop_gain"]
        assert public.memory_infinity_norm == expected["memory_infinity_norm"]
        assert public.configured_loop_gain == expected["configured_loop_gain"]


@pytest.mark.parametrize("field", ["tau_mood", "tau_uncertainty"])
def test_reference_and_public_fail_closed_for_subnormal_tau_ratio(field: str) -> None:
    case = next(item for item in FIXTURE["cases"] if item["id"] == "no_event_elapsed")
    raw = dict(PARAMETERS[case["parameter_set_id"]]["parameters"])
    raw[field] = 5e-324
    with pytest.raises(REFERENCE.ReferenceContractError):
        REFERENCE.reduce(case["state"], raw, case["transition"])
    with pytest.raises(EmotionValidationError):
        reduce_emotion_v2(_state(case["state"]), _parameters(raw), _transition(case["transition"]))


@pytest.mark.parametrize("case", FIXTURE["cases"], ids=lambda case: case["id"])
def test_reference_and_public_match_closed_static_cases(case: dict[str, object]) -> None:
    parameter_raw = PARAMETERS[case["parameter_set_id"]]["parameters"]
    expected = case["expected"]
    outcome = REFERENCE.evaluate_transition(case["state"], parameter_raw, case["transition"])
    assert outcome.substeps == expected["substeps"]
    assert outcome.event_impulse == (None if expected["reference_event_impulse"] is None else tuple(expected["reference_event_impulse"]))
    assert REFERENCE.canonical_bytes(outcome.state) == REFERENCE.canonical_bytes(expected["reference_state"])
    assert REFERENCE.canonical_digest(outcome.state) == expected["reference_state_sha256"]
    assert REFERENCE.canonical_digest(REFERENCE.normalize_transition(case["transition"])) == expected["transition_sha256"]
    assert REFERENCE.canonical_request_digest(case["state"], parameter_raw, case["transition"]) == expected["request_sha256"]
    state, parameters, transition = _state(case["state"]), _parameters(parameter_raw), _transition(case["transition"])
    actual = reduce_emotion_v2(state, parameters, transition)
    assert REFERENCE.canonical_bytes(asdict(actual)) == REFERENCE.canonical_bytes(expected["public_state"])
    assert actual.canonical_hash() == expected["public_state_sha256"]
    assert expected["reference_state"] == expected["public_state"]
    assert expected["reference_state_sha256"] == expected["public_state_sha256"]
    assert canonical_reduction_hash(state, parameters, transition) == expected["request_sha256"]
    if case["id"] == "zero_time_nonnovel":
        assert actual is state
