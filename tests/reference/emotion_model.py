"""Independent, standard-library-only oracle for the frozen Emotion V2 B1 reducer.

This module deliberately accepts plain JSON-shaped values.  It must never import
the application or consult ambient runtime state: Q5 loads it through an explicit
source loader so its only authority is the closed fixture supplied by the test.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
import hashlib
import json
import math


SIGNED_INT64_MAX = 2**63 - 1
COMPONENT_ORDER = ("joy", "sadness", "fear", "anger", "interest", "calm")
APPRAISAL_ORDER = (
    "valence", "goal_congruence", "novelty", "threat", "controllability",
    "agency_self_other", "social_relevance", "norm_conflict", "arousal",
)
DRIVE_ORDER = ("fatigue", "energy_deficit", "social_need", "curiosity")
TRAIT_ORDER = (
    "negative_sensitivity", "reward_sensitivity", "recovery_rate",
    "novelty_seeking", "affiliation",
)
MEMORY_SUMMARY_ORDER = (
    "dose_weighted_valence", "dose_weighted_arousal", "dose_confidence", "dose",
)


class ReferenceValidationError(ValueError):
    """Raised when a plain-value input is outside the frozen B1 contract."""


ReferenceContractError = ReferenceValidationError


def strict_json_loads(text: object) -> object:
    """Load a closed fixture without accepting JSON implementation extensions."""
    if not isinstance(text, str):
        raise ReferenceValidationError("fixture source must be text")

    def reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ReferenceValidationError(f"duplicate fixture key: {key}")
            result[key] = value
        return result

    def reject_constant(token: str) -> object:
        raise ReferenceValidationError(f"non-finite fixture number: {token}")

    try:
        return json.loads(
            text,
            object_pairs_hook=reject_duplicate_pairs,
            parse_constant=reject_constant,
        )
    except (TypeError, ValueError) as exc:
        if isinstance(exc, ReferenceValidationError):
            raise
        raise ReferenceValidationError("fixture is not strict JSON") from exc


@dataclass(frozen=True)
class ReferenceOutcome:
    state: dict[str, object]
    event_impulse: tuple[float, ...] | None
    substeps: int


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ReferenceValidationError(f"{label} must be a finite non-boolean number")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise ReferenceValidationError(f"{label} must be a finite non-boolean number") from exc
    if not math.isfinite(result):
        raise ReferenceValidationError(f"{label} must be finite")
    return result


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= SIGNED_INT64_MAX:
        raise ReferenceValidationError(f"{label} must be a signed int64 non-negative integer")
    return value


def _vector(value: object, label: str, length: int) -> tuple[float, ...]:
    if isinstance(value, (str, bytes)):
        raise ReferenceValidationError(f"{label} must be a {length}-element sequence")
    try:
        result = tuple(_number(item, f"{label}[{index}]") for index, item in enumerate(value))
    except TypeError as exc:
        raise ReferenceValidationError(f"{label} must be a {length}-element sequence") from exc
    if len(result) != length:
        raise ReferenceValidationError(f"{label} must have exactly {length} elements")
    return result


def _matrix(value: object, label: str, rows: int, columns: int) -> tuple[tuple[float, ...], ...]:
    if isinstance(value, (str, bytes)):
        raise ReferenceValidationError(f"{label} must be a matrix")
    try:
        result = tuple(_vector(row, f"{label}[{index}]", columns) for index, row in enumerate(value))
    except TypeError as exc:
        raise ReferenceValidationError(f"{label} must be a matrix") from exc
    if len(result) != rows:
        raise ReferenceValidationError(f"{label} must have exactly {rows} rows")
    return result


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ReferenceValidationError(f"{label} must be an object")
    return value


def _checked(value: float, label: str) -> float:
    if not math.isfinite(value):
        raise ReferenceValidationError(f"{label} must remain finite")
    return value


def _dot(left: tuple[float, ...], right: tuple[float, ...], label: str) -> float:
    if len(left) != len(right):
        raise ReferenceValidationError(f"{label} dimensions differ")
    total = 0.0
    for index in range(len(left)):
        # The order is frozen: product then sum for every component, never fsum
        # or a distributed q multiplication.
        product = _checked(left[index] * right[index], f"{label}[{index}] product")
        total = _checked(total + product, f"{label}[{index}] sum")
    return total


def _sigmoid(value: float) -> float:
    _checked(value, "sigmoid input")
    if value >= 0.0:
        return _checked(1.0 / _checked(1.0 + math.exp(-value), "sigmoid denominator"), "sigmoid result")
    exponent = _checked(math.exp(value), "sigmoid exponent")
    return _checked(exponent / _checked(1.0 + exponent, "sigmoid denominator"), "sigmoid result")


def _latent(activation: float, epsilon: float) -> float:
    if activation <= epsilon:
        activation = math.nextafter(epsilon, math.inf)
    elif activation >= 1.0 - epsilon:
        activation = math.nextafter(1.0 - epsilon, -math.inf)
    numerator = _checked(activation - epsilon, "latent numerator")
    upper = _checked(1.0 - epsilon, "latent upper")
    denominator = _checked(upper - activation, "latent denominator")
    try:
        return _checked(math.log(_checked(numerator / denominator, "latent ratio")), "latent result")
    except (OverflowError, ValueError, ZeroDivisionError) as exc:
        raise ReferenceValidationError("latent result is invalid") from exc


def _activation(latent: float, epsilon: float) -> float:
    span = _checked(1.0 - _checked(2.0 * epsilon, "activation epsilon span"), "activation span")
    return _checked(epsilon + _checked(span * _sigmoid(latent), "activation scaled sigmoid"), "activation result")


def _exp(value: float, label: str) -> float:
    try:
        return _checked(math.exp(value), label)
    except (OverflowError, ValueError) as exc:
        raise ReferenceValidationError(f"{label} is invalid") from exc


def _divide(left: float, right: float, label: str) -> float:
    try:
        return _checked(left / right, label)
    except (OverflowError, ValueError, ZeroDivisionError) as exc:
        raise ReferenceValidationError(f"{label} is invalid") from exc


def _parameters(raw: object) -> dict[str, object]:
    value = _mapping(raw, "parameters")
    parameter_set_id = value.get("parameter_set_id")
    if not isinstance(parameter_set_id, str) or not parameter_set_id:
        raise ReferenceValidationError("parameter_set_id must be non-empty")
    epsilon = _number(value.get("epsilon"), "epsilon")
    if not 0.0 < epsilon < 0.01:
        raise ReferenceValidationError("epsilon out of range")
    omega = _vector(value.get("omega"), "omega", 6)
    max_substep = _number(value.get("max_substep_seconds"), "max_substep_seconds")
    max_steps = value.get("max_substeps_per_transition")
    baseline = _vector(value.get("baseline_bias"), "baseline_bias", 6)
    w_drive = _matrix(value.get("w_drive"), "w_drive", 6, 4)
    w_trait = _matrix(value.get("w_trait"), "w_trait", 6, 5)
    coupling = _matrix(value.get("k"), "k", 6, 6)
    w_appraisal = _matrix(value.get("w_appraisal"), "w_appraisal", 6, 9)
    w_memory = _matrix(value.get("w_memory"), "w_memory", 6, 4)
    trait_mood = _number(value.get("trait_mood"), "trait_mood")
    mood_emotion = _vector(value.get("w_mood_emotion"), "w_mood_emotion", 6)
    mood_drive = _vector(value.get("w_mood_drive"), "w_mood_drive", 4)
    uncertainty_baseline = _number(value.get("uncertainty_baseline"), "uncertainty_baseline")
    tau_mood = _number(value.get("tau_mood"), "tau_mood")
    tau_uncertainty = _number(value.get("tau_uncertainty"), "tau_uncertainty")
    cap = _number(value.get("event_impulse_cap"), "event_impulse_cap")
    g_encode = _number(value.get("g_encode_max"), "g_encode_max")
    if (any(item <= 0.0 for item in omega) or max_substep <= 0.0
            or isinstance(max_steps, bool) or not isinstance(max_steps, int) or not 1 <= max_steps <= 10_000
            or any(sum(abs(item) for item in row) >= 4.0 for row in coupling)
            or not 0.0 <= uncertainty_baseline <= 1.0 or tau_mood <= 0.0
            or tau_uncertainty <= 0.0 or cap <= 0.0 or not 0.0 <= g_encode <= 1.0
            or max(sum(abs(item) for item in row) for row in w_memory) > 1.0):
        raise ReferenceValidationError("parameters violate the frozen B1 bounds")
    return {"parameter_set_id": parameter_set_id, "epsilon": epsilon, "omega": omega,
            "max_substep_seconds": max_substep, "max_substeps_per_transition": max_steps,
            "baseline_bias": baseline, "w_drive": w_drive, "w_trait": w_trait, "k": coupling,
            "w_appraisal": w_appraisal, "w_memory": w_memory, "trait_mood": trait_mood,
            "w_mood_emotion": mood_emotion, "w_mood_drive": mood_drive,
            "uncertainty_baseline": uncertainty_baseline, "tau_mood": tau_mood,
            "tau_uncertainty": tau_uncertainty, "event_impulse_cap": cap, "g_encode_max": g_encode}


def _state(raw: object, parameters: dict[str, object]) -> dict[str, object]:
    value = _mapping(raw, "state")
    activations = _vector(value.get("activations"), "activations", 6)
    velocity = _vector(value.get("velocity"), "velocity", 6)
    mood = _number(value.get("mood"), "mood")
    uncertainty = _number(value.get("uncertainty"), "uncertainty")
    parameter_set_id = value.get("parameter_set_id")
    epsilon = parameters["epsilon"]
    if (not isinstance(parameter_set_id, str) or parameter_set_id != parameters["parameter_set_id"]
            or any(not 0.0 < item < 1.0 for item in activations)
            or any(item < epsilon or item > 1.0 - epsilon for item in activations)
            or not -1.0 <= mood <= 1.0 or not 0.0 <= uncertainty <= 1.0):
        raise ReferenceValidationError("state violates the frozen B1 bounds")
    return {"activations": activations, "velocity": velocity, "mood": mood,
            "uncertainty": uncertainty, "last_update_ns": _integer(value.get("last_update_ns"), "last_update_ns"),
            "event_sequence": _integer(value.get("event_sequence"), "event_sequence"),
            "parameter_set_id": parameter_set_id}


def _transition(raw: object) -> dict[str, object]:
    value = _mapping(raw, "transition")
    appraisal = _mapping(value.get("appraisal"), "appraisal")
    appraisal_values = _vector(appraisal.get("values"), "appraisal.values", 9)
    confidence = _number(appraisal.get("confidence"), "appraisal.confidence")
    appraisal_uncertainty = _number(appraisal.get("uncertainty"), "appraisal.uncertainty")
    drives = _vector(value.get("drives"), "drives", 4)
    traits = _vector(value.get("traits"), "traits", 5)
    memory = _vector(value.get("memory_summary_vector"), "memory_summary_vector", 4)
    has_event, novel = value.get("has_event"), value.get("is_novel_event")
    elapsed = _number(value.get("elapsed_seconds"), "elapsed_seconds")
    if (not all((-1.0 <= item <= 1.0) if index in (0, 1, 5) else (0.0 <= item <= 1.0)
                for index, item in enumerate(appraisal_values))
            or not 0.0 <= confidence <= 1.0 or not 0.0 <= appraisal_uncertainty <= 1.0
            or any(not 0.0 <= item <= 1.0 for item in drives)
            or any(not 0.0 <= item <= 2.0 for item in traits)
            or not (-0.20 <= memory[0] <= 0.20 and 0.0 <= memory[1] <= 0.20
                    and 0.0 <= memory[2] <= 0.20 and 0.0 <= memory[3] <= 0.20)
            or abs(memory[0]) > memory[3] or memory[1] > memory[3] or memory[2] > memory[3]
            or (memory[3] == 0.0 and memory != (0.0, 0.0, 0.0, 0.0))
            or not isinstance(has_event, bool) or not isinstance(novel, bool) or (novel and not has_event)
            or elapsed < 0.0):
        raise ReferenceValidationError("transition violates the frozen B1 bounds")
    return {"appraisal": {"values": appraisal_values, "confidence": confidence, "uncertainty": appraisal_uncertainty},
            "drives": drives, "traits": traits, "memory_summary_vector": memory,
            "has_event": has_event, "is_novel_event": novel, "elapsed_seconds": elapsed,
            "wall_clock_ns": _integer(value.get("wall_clock_ns"), "wall_clock_ns")}


def reduce(state: object, parameters: object, transition: object) -> dict[str, object]:
    """Reduce one B1 transition using only the frozen plain-value contract."""
    p = _parameters(parameters)
    s = _state(state, p)
    t = _transition(transition)
    if t["is_novel_event"] and s["event_sequence"] == SIGNED_INT64_MAX:
        raise ReferenceValidationError("novel event exceeds signed int64 sequence")
    if t["elapsed_seconds"] == 0.0 and not t["is_novel_event"]:
        return s

    epsilon = p["epsilon"]
    y = tuple(_latent(item, epsilon) for item in s["activations"])
    velocity = s["velocity"]
    sequence = s["event_sequence"]
    if t["is_novel_event"]:
        q = _checked(t["appraisal"]["confidence"] * _checked(1.0 - t["appraisal"]["uncertainty"], "q complement"), "q")
        impulse = []
        for index in range(6):
            appraisal_dot = _dot(p["w_appraisal"][index], t["appraisal"]["values"], f"appraisal[{index}]")
            scaled_appraisal = _checked(q * appraisal_dot, f"scaled appraisal[{index}]")
            memory_dot = _dot(p["w_memory"][index], t["memory_summary_vector"], f"memory[{index}]")
            impulse.append(max(-p["event_impulse_cap"], min(p["event_impulse_cap"], _checked(scaled_appraisal + memory_dot, f"impulse[{index}]"))))
        y = tuple(_checked(y[index] + impulse[index], f"event latent[{index}]") for index in range(6))
        sequence += 1
    else:
        impulse = []
    activations = (s["activations"] if t["is_novel_event"] and not any(impulse)
                   else tuple(_activation(item, epsilon) for item in y))
    mood, uncertainty = s["mood"], s["uncertainty"]
    elapsed = t["elapsed_seconds"]
    if elapsed:
        try:
            steps = max(1, math.ceil(_divide(elapsed, p["max_substep_seconds"], "substep ratio")))
        except (OverflowError, ValueError) as exc:
            raise ReferenceValidationError("substep count is invalid") from exc
        if steps > p["max_substeps_per_transition"]:
            raise ReferenceValidationError("substep count exceeds configured bound")
        dt = _divide(elapsed, float(steps), "substep duration")
        for _ in range(steps):
            raw_target = []
            for index in range(6):
                drive_term = _dot(p["w_drive"][index], t["drives"], f"drive[{index}]")
                trait_term = _dot(p["w_trait"][index], t["traits"], f"trait[{index}]")
                coupling_term = _dot(p["k"][index], activations, f"coupling[{index}]")
                raw_target.append(_checked(_checked(_checked(p["baseline_bias"][index] + drive_term, "target drive") + trait_term, "target trait") - coupling_term, "target raw"))
            y_target = tuple(_latent(_activation(item, epsilon), epsilon) for item in raw_target)
            next_y, next_velocity = [], []
            for index in range(6):
                omega = p["omega"][index]
                difference = _checked(y[index] - y_target[index], f"critical d[{index}]")
                omega_difference = _checked(omega * difference, f"critical omega*d[{index}]")
                velocity_term = _checked(velocity[index] + omega_difference, f"critical velocity term[{index}]")
                decay = _exp(-_checked(omega * dt, f"critical omega*dt[{index}]"), f"critical decay[{index}]")
                y_inner = _checked(difference + _checked(velocity_term * dt, f"critical y*dt[{index}]"), f"critical y inner[{index}]")
                next_y.append(_checked(y_target[index] + _checked(y_inner * decay, f"critical y decay[{index}]"), f"critical y[{index}]"))
                v_inner = _checked(velocity[index] - _checked(_checked(omega * velocity_term, f"critical omega*velocity[{index}]") * dt, f"critical velocity*dt[{index}]"), f"critical v inner[{index}]")
                next_velocity.append(_checked(v_inner * decay, f"critical v[{index}]"))
            y, velocity = tuple(next_y), tuple(next_velocity)
            activations = tuple(_activation(item, epsilon) for item in y)
            mood_raw = _checked(_checked(p["trait_mood"] + _dot(p["w_mood_emotion"], activations, "mood emotion"), "mood emotion") + _dot(p["w_mood_drive"], t["drives"], "mood drive"), "mood raw")
            mood_target = max(-1.0, min(1.0, mood_raw))
            mood_ratio = _divide(dt, p["tau_mood"], "mood dt/tau")
            mood = _checked(mood_target + _checked((mood - mood_target) * _exp(-mood_ratio, "mood decay"), "mood decay term"), "mood update")
            uncertainty_target = t["appraisal"]["uncertainty"] if t["has_event"] else p["uncertainty_baseline"]
            uncertainty_ratio = _divide(dt, p["tau_uncertainty"], "uncertainty dt/tau")
            uncertainty = _checked(uncertainty_target + _checked((uncertainty - uncertainty_target) * _exp(-uncertainty_ratio, "uncertainty decay"), "uncertainty decay term"), "uncertainty update")
    if (not all(math.isfinite(item) and epsilon <= item <= 1.0 - epsilon for item in activations)
            or not all(math.isfinite(item) for item in velocity) or not -1.0 <= mood <= 1.0
            or not 0.0 <= uncertainty <= 1.0):
        raise ReferenceValidationError("reducer produced an invalid state")
    return {"activations": tuple(activations), "velocity": tuple(velocity), "mood": mood,
            "uncertainty": uncertainty, "last_update_ns": max(s["last_update_ns"], t["wall_clock_ns"]),
            "event_sequence": sequence, "parameter_set_id": s["parameter_set_id"]}


def _json_value(value: object) -> object:
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ReferenceValidationError("canonical mappings require string keys")
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    return value


def canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(_json_value(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ReferenceValidationError("value is not canonical finite JSON") from exc


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def reduction_hash(state: object, parameters: object, transition: object) -> str:
    normalized_parameters = _parameters(parameters)
    return canonical_sha256({
        "parameters": normalized_parameters,
        "state": _state(state, normalized_parameters),
        "transition": _transition(transition),
    })


def normalize_state(raw: dict[str, object]) -> dict[str, object]:
    """Normalize a state without supplying a hidden parameter profile."""
    value = _mapping(raw, "state")
    parameter_set_id = value.get("parameter_set_id")
    if not isinstance(parameter_set_id, str) or not parameter_set_id:
        raise ReferenceValidationError("parameter_set_id must be non-empty")
    activations = _vector(value.get("activations"), "activations", 6)
    if any(not 0.0 < item < 1.0 for item in activations):
        raise ReferenceValidationError("state activations must be interior")
    mood = _number(value.get("mood"), "mood")
    uncertainty = _number(value.get("uncertainty"), "uncertainty")
    if not -1.0 <= mood <= 1.0 or not 0.0 <= uncertainty <= 1.0:
        raise ReferenceValidationError("state bounds")
    return {"activations": activations, "velocity": _vector(value.get("velocity"), "velocity", 6),
            "mood": mood, "uncertainty": uncertainty,
            "last_update_ns": _integer(value.get("last_update_ns"), "last_update_ns"),
            "event_sequence": _integer(value.get("event_sequence"), "event_sequence"),
            "parameter_set_id": parameter_set_id}


def normalize_parameters(raw: dict[str, object]) -> dict[str, object]:
    return _parameters(raw)


def normalize_transition(raw: dict[str, object]) -> dict[str, object]:
    return _transition(raw)


def summarize_memory(total_dose: object, weighted_valence: object, weighted_arousal: object, confidence: object) -> tuple[float, float, float, float]:
    dose = _number(total_dose, "total_dose")
    valence = _number(weighted_valence, "weighted_valence")
    arousal = _number(weighted_arousal, "weighted_arousal")
    certainty = _number(confidence, "confidence")
    if not 0.0 <= dose <= 0.20 or not -1.0 <= valence <= 1.0 or not 0.0 <= arousal <= 1.0 or not 0.0 <= certainty <= 1.0:
        raise ReferenceValidationError("memory summary bounds")
    return (dose * valence, dose * arousal, dose * certainty, dose)


def configured_loop_gain(parameters: dict[str, object]) -> float:
    p = _parameters(parameters)
    norm = max(sum(abs(item) for item in row) for row in p["w_memory"])
    return _checked(p["g_encode_max"] * _checked(0.08 * _checked(0.20 * norm, "gain memory"), "gain retrieve"), "configured gain")


def event_impulse(parameters: dict[str, object], transition: dict[str, object]) -> tuple[float, ...]:
    p, t = _parameters(parameters), _transition(transition)
    q = _checked(t["appraisal"]["confidence"] * _checked(1.0 - t["appraisal"]["uncertainty"], "q complement"), "q")
    result = []
    for index in range(6):
        appraisal_dot = _dot(p["w_appraisal"][index], t["appraisal"]["values"], f"appraisal[{index}]")
        scaled = _checked(q * appraisal_dot, f"scaled appraisal[{index}]")
        memory_dot = _dot(p["w_memory"][index], t["memory_summary_vector"], f"memory[{index}]")
        result.append(max(-p["event_impulse_cap"], min(p["event_impulse_cap"], _checked(scaled + memory_dot, f"impulse[{index}]"))))
    return tuple(result)


def substeps(parameters: dict[str, object], elapsed_seconds: object) -> tuple[int, float]:
    p = _parameters(parameters)
    elapsed = _number(elapsed_seconds, "elapsed_seconds")
    if elapsed < 0.0:
        raise ReferenceValidationError("elapsed_seconds must be non-negative")
    ratio = _divide(elapsed, p["max_substep_seconds"], "substep ratio")
    try:
        count = max(1, math.ceil(ratio))
    except (OverflowError, ValueError) as exc:
        raise ReferenceValidationError("substep count is invalid") from exc
    if count > p["max_substeps_per_transition"]:
        raise ReferenceValidationError("substep count exceeds configured bound")
    return count, _divide(elapsed, float(count), "substep duration")


def evaluate_transition(state: dict[str, object], parameters: dict[str, object], transition: dict[str, object]) -> ReferenceOutcome:
    normalized_transition = _transition(transition)
    impulse = event_impulse(parameters, normalized_transition) if normalized_transition["is_novel_event"] else None
    count = 0 if normalized_transition["elapsed_seconds"] == 0.0 else substeps(parameters, normalized_transition["elapsed_seconds"])[0]
    return ReferenceOutcome(reduce(state, parameters, normalized_transition), impulse, count)


def canonical_bytes(value: object) -> bytes:
    return canonical_json_bytes(value)


def canonical_digest(value: object) -> str:
    return canonical_sha256(value)


def canonical_request_digest(state: object, parameters: object, transition: object) -> str:
    return reduction_hash(state, parameters, transition)


def trajectory_metrics(initial_state: object, states: object, epsilon: object) -> dict[str, object]:
    values = tuple(states)
    bound = _number(epsilon, "epsilon")
    if not values:
        raise ReferenceValidationError("trajectory must be non-empty")
    previous = normalize_state(initial_state)
    activation_totals = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    peak_abs_velocity = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    mood_total = 0.0
    uncertainty_total = 0.0
    saturation_count = 0
    variation = 0.0
    for raw_state in values:
        current = normalize_state(raw_state)
        state_variation = 0.0
        for component in range(6):
            activation = current["activations"][component]
            activation_totals[component] += activation
            velocity = abs(current["velocity"][component])
            if velocity > peak_abs_velocity[component]:
                peak_abs_velocity[component] = velocity
            if activation == bound or activation == 1.0 - bound:
                saturation_count += 1
            state_variation += abs(activation - previous["activations"][component])
        variation += state_variation
        mood_total += current["mood"]
        uncertainty_total += current["uncertainty"]
        previous = current
    count = float(len(values))
    means = tuple(total / count for total in activation_totals)
    saturation = float(saturation_count) / (count * 6.0)
    return {"saturation_fraction": saturation, "mean_activation": means,
            "peak_abs_velocity": tuple(peak_abs_velocity),
            "mean_mood": mood_total / count,
            "mean_uncertainty": uncertainty_total / count,
            "activation_total_variation": variation}
