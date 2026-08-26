from __future__ import annotations

from dataclasses import asdict
import importlib.util
from pathlib import Path
import sys

from core.emotion_v2 import AppraisalInputV2, EmotionParametersV2, EmotionStateV2, EmotionTransitionV2, reduce_emotion_v2


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
FIXTURE = REFERENCE.strict_json_loads(
    (ROOT / "fixtures" / "qa_emotion" / "emotion_v2_oracle_v1.json").read_text(encoding="utf-8")
)
HORIZON = FIXTURE["long_horizon"]
PARAMETERS_RAW = next(entry["parameters"] for entry in FIXTURE["parameter_sets"] if entry["id"] == HORIZON["parameter_set_id"])


def _validate_generator_authority() -> None:
    generator = HORIZON["generator"]
    assert HORIZON["id"] == "modular_4096"
    assert HORIZON["steps"] == 4096
    assert generator["formula_id"] == "emotion-modular-4096-v1"
    assert generator["index_origin"] == 0
    assert tuple(generator["valence_cycle"]) == (-0.85, -0.25, 0.15, 0.55, 0.9)
    assert tuple(generator["goal_congruence_cycle"]) == (0.65, -0.45, 0.1, -0.7)
    assert tuple(generator["agency_cycle"]) == (-0.8, 0.2, 0.75, -0.35, 0.0)
    assert tuple(generator["confidence_cycle"]) == (0.2, 0.65, 0.95, 0.5)
    assert tuple(generator["uncertainty_cycle"]) == (0.05, 0.4, 0.85, 0.25, 0.7)
    assert tuple(generator["dose_cycle"]) == (0.0, 0.05, 0.12, 0.2)
    assert tuple(generator["memory_valence_cycle"]) == (-1.0, -0.5, 0.25, 1.0)
    assert tuple(generator["memory_arousal_cycle"]) == (0.0, 0.35, 0.7, 1.0)
    assert tuple(generator["memory_confidence_cycle"]) == (0.0, 0.4, 0.8, 1.0)
    assert tuple(generator["traits"]) == (0.6, 1.25, 0.85, 1.4, 0.95)
    assert generator["novel_modulus"] == 7
    assert generator["event_absence_modulus"] == 3
    assert generator["elapsed_seconds"] == 0.125
    assert generator["clock_step_ns"] == 125_000_000


def _transition_at(offset: int) -> dict[str, object]:
    # The formula ID selects this frozen implementation; all declared constants
    # are consumed from the already-validated metadata rather than duplicated.
    generator = HORIZON["generator"]
    index = generator["index_origin"] + offset
    j = index % len(generator["dose_cycle"])
    novel = index % generator["novel_modulus"] == 0
    dose = generator["dose_cycle"][j] if novel else 0.0
    return {
        "appraisal": {"values": (generator["valence_cycle"][index % len(generator["valence_cycle"])], generator["goal_congruence_cycle"][index % len(generator["goal_congruence_cycle"])], (index % 8) / 7.0, ((3 * index + 1) % 9) / 8.0, ((5 * index + 2) % 11) / 10.0, generator["agency_cycle"][index % len(generator["agency_cycle"])], ((7 * index + 1) % 10) / 9.0, ((2 * index + 3) % 8) / 7.0, ((4 * index + 2) % 9) / 8.0), "confidence": generator["confidence_cycle"][index % len(generator["confidence_cycle"])], "uncertainty": generator["uncertainty_cycle"][index % len(generator["uncertainty_cycle"])]},
        "drives": ((index % 5) / 4.0, ((index + 1) % 4) / 3.0, ((index + 2) % 3) / 2.0, float(index % 2)),
        "traits": tuple(generator["traits"]),
        "memory_summary_vector": (dose * generator["memory_valence_cycle"][j], dose * generator["memory_arousal_cycle"][j], dose * generator["memory_confidence_cycle"][j], dose),
        "has_event": novel or index % generator["event_absence_modulus"] != 0,
        "is_novel_event": novel,
        "elapsed_seconds": generator["elapsed_seconds"],
        "wall_clock_ns": generator["clock_step_ns"] * (offset + 1),
    }


def _public_transition(raw: dict[str, object]) -> EmotionTransitionV2:
    value = dict(raw)
    value["appraisal"] = AppraisalInputV2(**value["appraisal"])
    return EmotionTransitionV2(**value)


def _ordered_trajectory_metrics(
    initial_state: dict[str, object], states: list[dict[str, object]], epsilon: float,
) -> dict[str, object]:
    activation_totals = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    peak_abs_velocity = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    mood_total = 0.0
    uncertainty_total = 0.0
    saturation_count = 0
    activation_total_variation = 0.0
    previous = initial_state
    for current in states:
        state_variation = 0.0
        for component in range(6):
            activation = current["activations"][component]
            activation_totals[component] += activation
            velocity = abs(current["velocity"][component])
            if velocity > peak_abs_velocity[component]:
                peak_abs_velocity[component] = velocity
            if activation == epsilon or activation == 1.0 - epsilon:
                saturation_count += 1
            state_variation += abs(
                activation - previous["activations"][component]
            )
        activation_total_variation += state_variation
        mood_total += current["mood"]
        uncertainty_total += current["uncertainty"]
        previous = current
    count = float(len(states))
    return {
        "saturation_fraction": float(saturation_count) / (count * 6.0),
        "mean_activation": tuple(total / count for total in activation_totals),
        "peak_abs_velocity": tuple(peak_abs_velocity),
        "mean_mood": mood_total / count,
        "mean_uncertainty": uncertainty_total / count,
        "activation_total_variation": activation_total_variation,
    }


def test_exactly_4096_reference_and_4096_public_adjudicated_transitions() -> None:
    _validate_generator_authority()
    generator = HORIZON["generator"]
    reference_state = HORIZON["initial_state"]
    public_state = EmotionStateV2(**reference_state)
    parameters = EmotionParametersV2(**PARAMETERS_RAW)
    trajectory = [reference_state]
    novel_count = 0
    for offset in range(HORIZON["steps"]):
        raw = _transition_at(offset)
        if raw["is_novel_event"]:
            novel_count += 1
        reference_state = REFERENCE.reduce(reference_state, PARAMETERS_RAW, raw)
        public_state = reduce_emotion_v2(public_state, parameters, _public_transition(raw))
        trajectory.append(reference_state)
        step = offset + 1
        assert asdict(public_state) == reference_state
        assert public_state.event_sequence == HORIZON["initial_state"]["event_sequence"] + novel_count
        assert public_state.last_update_ns == generator["clock_step_ns"] * step
        assert all(parameters.epsilon <= value <= 1.0 - parameters.epsilon for value in public_state.activations)
        assert -1.0 <= public_state.mood <= 1.0 and 0.0 <= public_state.uncertainty <= 1.0
        if str(step) in HORIZON["expected"]["reference_checkpoint_sha256"]:
            assert REFERENCE.canonical_digest(reference_state) == HORIZON["expected"]["reference_checkpoint_sha256"][str(step)]
            assert public_state.canonical_hash() == HORIZON["expected"]["public_checkpoint_sha256"][str(step)]
    expected = HORIZON["expected"]
    assert REFERENCE.canonical_bytes(reference_state) == REFERENCE.canonical_bytes(expected["reference_final_state"])
    assert REFERENCE.canonical_digest(reference_state) == expected["reference_final_sha256"]
    assert REFERENCE.canonical_bytes(asdict(public_state)) == REFERENCE.canonical_bytes(expected["public_final_state"])
    assert public_state.canonical_hash() == expected["public_final_sha256"]
    assert expected["reference_checkpoint_sha256"] == expected["public_checkpoint_sha256"]
    assert expected["reference_final_state"] == expected["public_final_state"]
    assert expected["reference_final_sha256"] == expected["public_final_sha256"]
    metrics = REFERENCE.trajectory_metrics(
        HORIZON["initial_state"], trajectory[1:], parameters.epsilon,
    )
    independent_metrics = _ordered_trajectory_metrics(
        HORIZON["initial_state"], trajectory[1:], parameters.epsilon,
    )
    assert metrics == independent_metrics
    for key, value in expected["metrics"].items():
        if isinstance(value, list):
            assert metrics[key] == tuple(value)
        else:
            assert metrics[key] == value
