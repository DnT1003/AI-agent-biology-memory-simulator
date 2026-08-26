from __future__ import annotations

import ast
import hashlib
import importlib.util
from pathlib import Path
import sys

import pytest

from core.emotion_v2 import EmotionParametersV2, EmotionStateV2, EmotionValidationError


REFERENCE_PATH = Path(__file__).parents[1] / "reference" / "emotion_model.py"


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


def _independent_parameters() -> dict[str, object]:
    zeros6 = [0.0] * 6
    return {
        "parameter_set_id": "independent-v1", "epsilon": 0.001,
        "omega": [1.0] * 6, "max_substep_seconds": 0.5,
        "max_substeps_per_transition": 8, "baseline_bias": zeros6,
        "w_drive": [[0.0] * 4 for _ in range(6)],
        "w_trait": [[0.0] * 5 for _ in range(6)],
        "k": [[0.0] * 6 for _ in range(6)],
        "w_appraisal": [[1.0] + [0.0] * 8] + [[0.0] * 9 for _ in range(5)],
        "w_memory": [[0.5, 0.0, 0.0, 0.0]] + [[0.0] * 4 for _ in range(5)],
        "trait_mood": 0.0, "w_mood_emotion": zeros6, "w_mood_drive": [0.0] * 4,
        "uncertainty_baseline": 0.5, "tau_mood": 1.0, "tau_uncertainty": 1.0,
        "event_impulse_cap": 0.25, "g_encode_max": 0.75,
    }


def _independent_transition() -> dict[str, object]:
    return {
        "appraisal": {"values": [0.4] + [0.0] * 8, "confidence": 0.5, "uncertainty": 0.2},
        "drives": [0.0] * 4, "traits": [0.0] * 5,
        "memory_summary_vector": [0.1, 0.0, 0.0, 0.1],
        "has_event": True, "is_novel_event": True,
        "elapsed_seconds": 1.2, "wall_clock_ns": 1,
    }


def test_reference_is_frozen_loader_only_and_has_no_project_or_ambient_authority() -> None:
    tree = ast.parse(REFERENCE_PATH.read_text(encoding="utf-8"))
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module != "__future__":
            imports.append(node.module or "")
    assert set(imports) == {"dataclasses", "hashlib", "json", "math"}
    forbidden = {"core", "os", "pathlib", "subprocess", "sys", "importlib", "time", "random"}
    assert not (set(imports) & forbidden)
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    assert not (names & {"open", "exec", "eval", "__import__", "getenv", "environ"})
    reference = REFERENCE
    assert reference.COMPONENT_ORDER == ("joy", "sadness", "fear", "anger", "interest", "calm")


def test_reference_preserves_frozen_sequential_appraisal_order() -> None:
    reference = REFERENCE
    left = (1.0e16, -1.0e16, 1.0)
    right = (1.0, 1.0, 1.0)
    assert reference._dot(left, right, "order") == 1.0
    assert reference._dot(tuple(reversed(left)), tuple(reversed(right)), "order") == 0.0


def test_reference_rejects_non_string_nested_canonical_mapping_keys() -> None:
    with pytest.raises(REFERENCE.ReferenceContractError):
        REFERENCE.canonical_bytes({"outer": {1: "forbidden"}})


def test_hand_written_canonical_utf8_bytes_and_fixed_sha256() -> None:
    # This byte literal is intentionally not produced by either JSON serializer.
    expected_bytes = b'{"a":[1,true],"\xc3\xa9":"caf\xc3\xa9"}'
    expected_sha256 = "70911a36b6bf0cff5c9174ed34d0e1d0980d3a19827565f0b851d2e9257a94ed"
    value = {"é": "café", "a": [1, True]}
    assert REFERENCE.canonical_bytes(value) == expected_bytes
    assert hashlib.sha256(expected_bytes).hexdigest() == expected_sha256
    assert REFERENCE.canonical_digest(value) == expected_sha256


def test_summarize_memory_has_independently_calculated_components() -> None:
    assert REFERENCE.summarize_memory(0.125, -0.4, 0.8, 0.6) == (-0.05, 0.1, 0.075, 0.125)
    assert REFERENCE.summarize_memory(0.0, -1.0, 1.0, 1.0) == (0.0, 0.0, 0.0, 0.0)


def test_reference_and_public_accept_nonempty_whitespace_ids_but_reject_empty_or_nonstring_ids() -> None:
    parameters = _independent_parameters()
    parameters["parameter_set_id"] = " \t"
    assert REFERENCE.normalize_parameters(parameters)["parameter_set_id"] == " \t"
    assert EmotionParametersV2(**parameters).parameter_set_id == " \t"
    state = {
        "activations": [0.5] * 6, "velocity": [0.0] * 6,
        "mood": 0.0, "uncertainty": 0.0, "last_update_ns": 0,
        "event_sequence": 0, "parameter_set_id": " \t",
    }
    assert REFERENCE.normalize_state(state)["parameter_set_id"] == " \t"
    assert EmotionStateV2(**state).parameter_set_id == " \t"
    for invalid in ("", 7):
        bad_parameters = {**parameters, "parameter_set_id": invalid}
        bad_state = {**state, "parameter_set_id": invalid}
        with pytest.raises(REFERENCE.ReferenceContractError):
            REFERENCE.normalize_parameters(bad_parameters)
        with pytest.raises(EmotionValidationError):
            EmotionParametersV2(**bad_parameters)
        with pytest.raises(REFERENCE.ReferenceContractError):
            REFERENCE.normalize_state(bad_state)
        with pytest.raises(EmotionValidationError):
            EmotionStateV2(**bad_state)


def test_event_impulse_substeps_and_configured_gain_have_direct_independent_answers() -> None:
    parameters, transition = _independent_parameters(), _independent_transition()
    # q=.5*(1-.2)=.4; impulse[0]=.4*.4+.5*.1=.21.
    assert REFERENCE.event_impulse(parameters, transition) == (0.21000000000000002, 0.0, 0.0, 0.0, 0.0, 0.0)
    assert REFERENCE.substeps(parameters, 1.2) == (3, 0.39999999999999997)
    # .75 * .08 * (.20 * .50)
    assert REFERENCE.configured_loop_gain(parameters) == 0.006


def test_trajectory_metrics_have_hand_calculated_literal_results() -> None:
    first = {
        "activations": [0.2, 0.3, 0.4, 0.5, 0.6, 0.7],
        "velocity": [-1.0, 0.2, -0.3, 0.4, -0.5, 0.6],
        "mood": -0.5, "uncertainty": 0.2, "last_update_ns": 1,
        "event_sequence": 0, "parameter_set_id": "independent-v1",
    }
    second = {
        "activations": [0.3, 0.2, 0.5, 0.4, 0.7, 0.6],
        "velocity": [0.5, -0.4, 0.7, -0.8, 0.9, -1.0],
        "mood": 0.5, "uncertainty": 0.8, "last_update_ns": 2,
        "event_sequence": 1, "parameter_set_id": "independent-v1",
    }
    assert REFERENCE.trajectory_metrics(first, [second], 0.2) == {
        "saturation_fraction": 1.0 / 6.0,
        "mean_activation": (0.3, 0.2, 0.5, 0.4, 0.7, 0.6),
        "peak_abs_velocity": (0.5, 0.4, 0.7, 0.8, 0.9, 1.0),
        "mean_mood": 0.5,
        "mean_uncertainty": 0.8,
        "activation_total_variation": 0.5999999999999999,
    }


def test_trajectory_metric_order_discriminates_ordinary_addition_from_python_sum() -> None:
    values = [0.5, 5e-17, 5e-17]
    states = []
    for index, value in enumerate(values, start=1):
        states.append({
            "activations": [value, 0.5, 0.5, 0.5, 0.5, 0.5],
            "velocity": [0.0] * 6,
            "mood": 0.0,
            "uncertainty": 0.0,
            "last_update_ns": index,
            "event_sequence": 0,
            "parameter_set_id": "ordered-metrics-v1",
        })
    initial = {**states[0], "activations": [0.25] * 6, "last_update_ns": 0}
    ordinary_total = 0.0
    for value in values:
        ordinary_total += value
    builtin_total = sum(values)
    assert ordinary_total.hex() == "0x1.0000000000000p-1"
    assert builtin_total.hex() == "0x1.0000000000001p-1"
    metrics = REFERENCE.trajectory_metrics(initial, states, 0.001)
    assert metrics["mean_activation"][0] == ordinary_total / 3.0
    assert metrics["mean_activation"][0] != builtin_total / 3.0
