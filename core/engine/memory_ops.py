import json
import copy
import hashlib
import math
import os
import re
import time
import random
import uuid
from dataclasses import dataclass
from typing import List, Optional
from colorama import Fore, Style
from config import Config
from components.vector_store import MemoryStoreError
from core.memory import MemoryTrace, MemoryType
from core.memory_context import (
    MemoryAccessContext,
    MemoryAccessError,
    MemoryPrivacy,
    MemoryScope,
    current_memory_context,
    memory_context_scope,
)
from core.prompts import get_semantic_drift_prompt, get_sleep_dream_prompt
from core.agent_state import AgentState
from core.self_model import validate_calibration_updates
from core.operation_ledger import (
    OperationCorruptionError,
    OperationRecord,
    OperationStatus,
    QuarantineReason,
)


_BELIEF_CONTENT_PREFIX = "Niềm tin cốt lõi (Belief): "
_BELIEF_DELETE_INTENT_CONTENT = "Mutation delete intent"
_BELIEF_MERGE_INTENT_PREFIX = "Mutation merge intent: "
_BELIEF_MANIFEST_ID_VERSION = "v2"
_DREAM_MANIFEST_ID_VERSION = "v3"
_DREAM_PLAN_VERSION = 1
_DREAM_OPERATION_TYPE = "dream_consolidation"
_MAX_DREAM_RAW_RESPONSE_CHARS = 64 * 1024
_MAX_DREAM_INSIGHTS = 16
_MAX_DREAM_CONCLUSION_CHARS = 1024
_MAX_DREAM_REASONING_CHARS = 2048
_MAX_DREAM_TAGS = 8
_MAX_DREAM_TAG_CHARS = 64
_MAX_DREAM_PARENT_CONTENT_CHARS = 8192
_MAX_DREAM_PROMPT_CHARS = 64 * 1024
_REAPPRAISAL_PLAN_VERSION = 1
_REAPPRAISAL_OPERATION_TYPE = "cognitive_reappraisal"
_REAPPRAISAL_LEGACY_MARKER = "[ToReevaluate]"
_REAPPRAISAL_CHILD_PREFIX = "Niềm tin cốt lõi (Belief): "
_MAX_REAPPRAISAL_RESPONSE_CHARS = 64 * 1024
_MAX_REAPPRAISAL_REASONING_CHARS = 2_048
_MAX_REAPPRAISAL_BELIEF_CHARS = 2_048
_MAX_REAPPRAISAL_PARENT_CONTENT_CHARS = 16 * 1024
_REAPPRAISAL_MARKER_RE = re.compile(
    r"\A\[ToReevaluate:"
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
    r"\]\Z"
)


class _DreamPlanError(ValueError):
    """A durable dream plan is structurally or semantically invalid."""


class _DuplicateDreamKey(ValueError):
    pass


def _dream_object_without_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateDreamKey(key)
        result[key] = value
    return result


def _dream_reject_non_finite(value):
    raise ValueError(f"non-finite JSON number: {value}")


def _canonical_json(value) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )


def _bounded_dream_text(
    value: object,
    *,
    field: str,
    max_chars: int,
) -> str:
    """Return bounded UTF-8 text that is safe for prompts and vector stores."""

    if type(value) is not str:
        raise _DreamPlanError(f"dream {field} is not text")
    normalized = value.strip()
    if not normalized or len(normalized) > max_chars:
        raise _DreamPlanError(f"dream {field} is not bounded text")
    try:
        normalized.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise _DreamPlanError(f"dream {field} is not valid UTF-8") from exc
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise _DreamPlanError(f"dream {field} contains control characters")
    return normalized


def _dream_parent_frame(parent_ids: List[str]) -> str:
    """Encode an ordered source set without delimiter ambiguity."""

    return _canonical_json({
        "parent_ids": list(parent_ids),
        "version": _DREAM_MANIFEST_ID_VERSION,
    })


def _dream_consolidation_id(parent_ids: List[str]) -> str:
    return str(uuid.uuid5(
        uuid.NAMESPACE_URL,
        "aura:memory-consolidation:" + _dream_parent_frame(parent_ids),
    ))


def _dream_operation_id(consolidation_id: str) -> str:
    return f"dream:{consolidation_id}"


def _belief_parent_frame(parent_ids: List[str]) -> str:
    """Encode an ordered parent set without delimiter ambiguity."""

    return json.dumps(
        list(parent_ids),
        ensure_ascii=True,
        separators=(",", ":"),
    )


def _belief_delete_intent_id(parent_ids: List[str]) -> str:
    return str(uuid.uuid5(
        uuid.NAMESPACE_URL,
        "aura:belief-delete-intent:"
        + _BELIEF_MANIFEST_ID_VERSION
        + ":"
        + _belief_parent_frame(parent_ids),
    ))


def _belief_merge_child_id(parent_ids: List[str], new_content: str) -> str:
    operation_frame = json.dumps(
        [list(parent_ids), new_content],
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return str(uuid.uuid5(
        uuid.NAMESPACE_URL,
        "aura:belief-merge:"
        + _BELIEF_MANIFEST_ID_VERSION
        + ":"
        + operation_frame,
    ))


@dataclass(frozen=True)
class MemoryHit:
    """One ranked, read-only selection in a recall plan."""

    score: float
    memory: MemoryTrace
    is_associative: bool = False


@dataclass(frozen=True)
class RecallPlan:
    """Immutable selection result; applying it is a separate operation."""

    hits: tuple[MemoryHit, ...]
    mood: float
    dynamic_top_k: int
    return_limit: int
    throttle_level: str
    chronological_error_type: Optional[str]
    force_local: bool


@dataclass(frozen=True)
class SleepEnrichmentFailure:
    """Safe diagnostic metadata for one best-effort post-commit phase."""

    phase: str
    cause_type: str


@dataclass(frozen=True)
class SleepOutcome:
    """The latest sleep saga result without exposing exception messages."""

    sleep_committed: bool
    committed_at: Optional[float] = None
    degraded_phases: tuple[SleepEnrichmentFailure, ...] = ()


class SleepMaintenanceError(RuntimeError):
    """A critical sleep phase failed before the sleep state was committed."""

    def __init__(self, phase: str, cause: BaseException):
        self.phase = phase
        self.sleep_committed = False
        self.cause_type = type(cause).__name__
        super().__init__(
            "Sleep maintenance failed before commit "
            f"phase={phase} cause_type={self.cause_type}"
        )


class CalibrationError(RuntimeError):
    """A safe, typed failure from one calibration phase."""

    def __init__(self, phase: str, cause: BaseException):
        self.phase = phase
        self.cause_type = type(cause).__name__
        super().__init__(
            "Calibration failed "
            f"phase={phase} cause_type={self.cause_type}"
        )


_MAX_CALIBRATION_RESPONSE_CHARS = 65_536
_MAX_CALIBRATION_ANALYSIS_CHARS = 4_096


def _calibration_object_without_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("calibration JSON contains a duplicate field")
        result[key] = value
    return result


def _parse_calibration_payload(raw_response):
    if not isinstance(raw_response, str):
        raise TypeError("calibration response must be text")
    if len(raw_response) > _MAX_CALIBRATION_RESPONSE_CHARS:
        raise ValueError("calibration response is too large")

    json_text = raw_response.strip()
    if json_text.startswith("```json") and json_text.endswith("```"):
        json_text = json_text[len("```json"):-len("```")].strip()
    elif json_text.startswith("```") and json_text.endswith("```"):
        json_text = json_text[len("```"):-len("```")].strip()

    def reject_non_finite(_value):
        raise ValueError("calibration JSON contains a non-finite number")

    payload = json.loads(
        json_text,
        object_pairs_hook=_calibration_object_without_duplicates,
        parse_constant=reject_non_finite,
    )
    if type(payload) is not dict:
        raise TypeError("calibration payload must be an object")
    if set(payload) - {"analysis", "updates"}:
        raise ValueError("calibration payload contains an unknown field")
    if "updates" not in payload or type(payload["updates"]) is not dict:
        raise TypeError("calibration updates must be an object")

    analysis = payload.get("analysis", "")
    if not isinstance(analysis, str):
        raise TypeError("calibration analysis must be text")
    if len(analysis) > _MAX_CALIBRATION_ANALYSIS_CHARS:
        raise ValueError("calibration analysis is too large")

    return validate_calibration_updates(payload["updates"])


def _memory_policy(trace: MemoryTrace) -> tuple[str, str] | None:
    """Return the durable policy of a normal, queryable trace."""

    scope = str(getattr(trace, "scope", "") or "")
    privacy = str(getattr(trace, "privacy", "") or "")
    if scope not in {MemoryScope.AGENT.value, MemoryScope.OWNER.value}:
        return None
    if privacy != MemoryPrivacy.STANDARD.value:
        # Legacy-unknown records stay quarantined. Derivation must never turn
        # uncertain source data into a new standard record.
        return None
    return scope, privacy


def _homogeneous_policy(
    traces: List[MemoryTrace],
) -> tuple[str, str] | None:
    if not traces:
        return None
    policies = {_memory_policy(trace) for trace in traces}
    if None in policies or len(policies) != 1:
        return None
    return next(iter(policies))


def _memory_is_writable(trace: MemoryTrace) -> bool:
    """Cheap call-site guard; MemoryManager remains the authority."""

    context = current_memory_context()
    if context.private_ephemeral or _memory_policy(trace) is None:
        return False
    if context.write_scope is not None:
        writable_scopes = {context.write_scope.value}
    else:
        writable_scopes = {scope.value for scope in context.read_scopes}
    return trace.scope in writable_scopes


def _write_context_for_scope(
    scope: str,
    *,
    origin_kind: str,
    origin_source: str,
    carry_source_event: bool = True,
) -> MemoryAccessContext:
    """Narrow a maintenance operation to one already-validated scope."""

    active = current_memory_context()
    target_scope = MemoryScope(scope)
    if target_scope not in active.read_scopes:
        raise MemoryAccessError("derived_memory_write", "scope_not_readable")
    if active.write_scope is not None and active.write_scope != target_scope:
        # A request-scoped owner operation must never promote itself into an
        # agent writer. Cross-scope maintenance starts with write_scope=None
        # and may then narrow to exactly one validated source policy.
        raise MemoryAccessError("derived_memory_write", "scope_widening")
    return MemoryAccessContext(
        read_scopes=active.read_scopes,
        write_scope=target_scope,
        private_ephemeral=active.private_ephemeral,
        local_only=active.local_only,
        origin_kind=origin_kind,
        origin_source=origin_source,
        source_event_id=(active.source_event_id if carry_source_event else None),
    )


def _restore_trace_state(trace: MemoryTrace, state: dict) -> None:
    """Restore a mutable trace after its durable write failed."""

    trace.__dict__.clear()
    trace.__dict__.update(copy.deepcopy(state))


def _durable_trace_matches(actual: MemoryTrace | None, expected: MemoryTrace) -> bool:
    """Compare fields that grant a derived record destructive authority."""

    if actual is None:
        return False
    return (
        str(actual.id) == str(expected.id)
        and actual.content == expected.content
        and actual.type == expected.type
        and _memory_policy(actual) == _memory_policy(expected)
        and actual.origin_kind == expected.origin_kind
        and actual.origin_source == expected.origin_source
        and actual.consolidation_id == expected.consolidation_id
        and list(actual.consolidation_parent_ids)
        == list(expected.consolidation_parent_ids)
        and actual.consolidation_expected_derived_count
        == expected.consolidation_expected_derived_count
        and list(actual.provenance_parent_ids)
        == list(expected.provenance_parent_ids)
    )


def _valid_consolidation_child_id(
    trace: MemoryTrace,
    consolidation_id: str,
    expected_count: int,
) -> bool:
    """Verify that a legacy child ID agrees with its persisted memory type."""

    try:
        memory_type = MemoryType(trace.type)
    except (TypeError, ValueError):
        return False
    if memory_type == MemoryType.SEMANTIC:
        kind = "semantic"
    elif memory_type == MemoryType.CORE:
        kind = "core"
    else:
        return False
    return str(trace.id) in {
        str(uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"{consolidation_id}:{kind}:{item_index}",
        ))
        for item_index in range(expected_count)
    }


def _valid_consolidation_child_set(
    traces: List[MemoryTrace],
    consolidation_id: str,
    expected_count: int,
) -> bool:
    """Reject impossible/gapped deterministic M2.1 child manifests."""

    if expected_count > 128 or len(traces) > expected_count:
        return False
    semantic_indices: set[int] = set()
    core_indices: set[int] = set()
    for trace in traces:
        matched = None
        for item_index in range(expected_count):
            for memory_type, kind in (
                (MemoryType.SEMANTIC, "semantic"),
                (MemoryType.CORE, "core"),
            ):
                expected_id = str(uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"{consolidation_id}:{kind}:{item_index}",
                ))
                if str(trace.id) == expected_id:
                    matched = memory_type, item_index
                    break
            if matched is not None:
                break
        if matched is None:
            return False
        try:
            actual_type = MemoryType(trace.type)
        except (TypeError, ValueError):
            return False
        if actual_type != matched[0]:
            return False
        if actual_type == MemoryType.SEMANTIC:
            semantic_indices.add(matched[1])
        else:
            core_indices.add(matched[1])
    return (
        semantic_indices == set(range(len(semantic_indices)))
        and core_indices.issubset(semantic_indices)
    )


def _dream_parent_fingerprint(trace: MemoryTrace) -> str:
    """Fingerprint every source field that authorizes the planned inference.

    Strength and consolidation markers are intentionally excluded: strength
    can decay while a recoverable plan waits, and the marker is the operation's
    own final side effect. Content, temporal identity, policy, and provenance
    must remain exact.
    """

    record_id = getattr(trace, "id", None)
    content = getattr(trace, "content", None)
    if (
        type(record_id) is not str
        or not record_id
        or len(record_id) > 512
        or type(content) is not str
        or len(content) > _MAX_DREAM_PARENT_CONTENT_CHARS
    ):
        raise _DreamPlanError("dream parent identity is invalid")
    try:
        record_id.encode("utf-8", errors="strict")
        content.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise _DreamPlanError("dream parent text is not valid UTF-8") from exc
    if any(ord(character) == 0 for character in content):
        raise _DreamPlanError("dream parent content contains a null character")
    try:
        memory_type = MemoryType(getattr(trace, "type", None)).value
    except (TypeError, ValueError) as exc:
        raise _DreamPlanError("dream parent type is invalid") from exc
    if memory_type != MemoryType.EPISODIC.value:
        raise _DreamPlanError("dream parent is not episodic")
    created_at = getattr(trace, "created_at", None)
    if (
        isinstance(created_at, bool)
        or not isinstance(created_at, (int, float))
        or not math.isfinite(float(created_at))
    ):
        raise _DreamPlanError("dream parent timestamp is invalid")
    policy = _memory_policy(trace)
    if policy is None:
        raise _DreamPlanError("dream parent policy is invalid")
    origin_kind = getattr(trace, "origin_kind", None)
    origin_source = getattr(trace, "origin_source", None)
    source_event_id = getattr(trace, "source_event_id", None)
    provenance = getattr(trace, "provenance_parent_ids", None)
    if (
        type(origin_kind) is not str
        or not origin_kind.strip()
        or type(origin_source) is not str
        or not origin_source.strip()
        or (
            source_event_id is not None
            and (type(source_event_id) is not str or not source_event_id.strip())
        )
        or type(provenance) is not list
        or any(type(parent_id) is not str or not parent_id for parent_id in provenance)
        or len(set(provenance)) != len(provenance)
    ):
        raise _DreamPlanError("dream parent provenance is invalid")
    payload = {
        "content": content,
        "created_at": float(created_at),
        "id": record_id,
        "origin_kind": origin_kind,
        "origin_source": origin_source,
        "privacy": policy[1],
        "provenance_parent_ids": list(provenance),
        "scope": policy[0],
        "source_event_id": source_event_id,
        "type": memory_type,
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _dream_trace_to_spec(trace: MemoryTrace) -> dict:
    """Serialize every persistent MemoryTrace field into an immutable plan."""

    spec = {}
    for field_name in MemoryTrace.__dataclass_fields__:
        value = getattr(trace, field_name)
        if hasattr(value, "value") and isinstance(value.value, str):
            value = value.value
        elif isinstance(value, list):
            value = list(value)
        spec[field_name] = value
    # This also rejects non-finite values before the plan reaches SQLite.
    _canonical_json(spec)
    return spec


def _dream_trace_from_spec(
    spec: object,
    *,
    consolidation_id: str,
    parent_ids: List[str],
    policy: tuple[str, str],
    expected_count: int,
) -> MemoryTrace:
    if type(spec) is not dict or set(spec) != set(MemoryTrace.__dataclass_fields__):
        raise _DreamPlanError("dream child shape is invalid")
    try:
        trace = MemoryTrace(**copy.deepcopy(spec))
    except (TypeError, ValueError, OverflowError) as exc:
        raise _DreamPlanError("dream child cannot be decoded") from exc
    try:
        if _canonical_json(_dream_trace_to_spec(trace)) != _canonical_json(spec):
            raise _DreamPlanError("dream child is not canonical")
    except (TypeError, ValueError, OverflowError) as exc:
        if isinstance(exc, _DreamPlanError):
            raise
        raise _DreamPlanError("dream child is not canonical") from exc
    if (
        trace.consolidation_id != consolidation_id
        or trace.consolidation_parent_ids != parent_ids
        or trace.consolidation_expected_derived_count != expected_count
        or trace.scope != policy[0]
        or trace.privacy != policy[1]
        or trace.origin_kind != "consolidation"
        or trace.origin_source != "sleep"
        or trace.source_event_id is not None
        or trace.provenance_parent_ids != parent_ids
        or trace.is_consolidated_source
        or trace.consolidated_at is not None
        or not trace.is_flashbulb
    ):
        raise _DreamPlanError("dream child authority fields are invalid")
    return trace


def _dream_trace_exact_match(
    actual: MemoryTrace | None,
    expected: MemoryTrace,
) -> bool:
    if actual is None:
        return False
    try:
        return _canonical_json(_dream_trace_to_spec(actual)) == _canonical_json(
            _dream_trace_to_spec(expected)
        )
    except (AttributeError, TypeError, ValueError, OverflowError):
        return False


def _parse_dream_insights(raw_response: object) -> list[dict]:
    """Validate the entire inference batch before any durable mutation."""

    if type(raw_response) is not str or len(raw_response) > _MAX_DREAM_RAW_RESPONSE_CHARS:
        raise _DreamPlanError("dream response is not bounded text")
    json_text = raw_response.strip()
    if json_text.startswith("```json") and json_text.endswith("```"):
        json_text = json_text[len("```json"):-len("```")].strip()
    elif json_text.startswith("```") and json_text.endswith("```"):
        json_text = json_text[len("```"):-len("```")].strip()
    try:
        payload = json.loads(
            json_text,
            object_pairs_hook=_dream_object_without_duplicates,
            parse_constant=_dream_reject_non_finite,
        )
    except (json.JSONDecodeError, TypeError, ValueError, RecursionError) as exc:
        raise _DreamPlanError("dream response is invalid JSON") from exc
    if type(payload) is not list or not 1 <= len(payload) <= _MAX_DREAM_INSIGHTS:
        raise _DreamPlanError("dream response must be a bounded non-empty list")

    validated = []
    for item in payload:
        if type(item) is not dict or set(item) - {"conclusion", "reasoning", "tags"}:
            raise _DreamPlanError("dream insight shape is invalid")
        conclusion = item.get("conclusion")
        reasoning = item.get("reasoning")
        tags = item.get("tags", [])
        if (
            type(tags) is not list
            or len(tags) > _MAX_DREAM_TAGS
        ):
            raise _DreamPlanError("dream insight values are invalid")
        conclusion = _bounded_dream_text(
            conclusion,
            field="conclusion",
            max_chars=_MAX_DREAM_CONCLUSION_CHARS,
        )
        reasoning = _bounded_dream_text(
            reasoning,
            field="reasoning",
            max_chars=_MAX_DREAM_REASONING_CHARS,
        )
        safe_tags = []
        for tag in tags:
            safe_tags.append(_bounded_dream_text(
                tag,
                field="tag",
                max_chars=_MAX_DREAM_TAG_CHARS,
            ))
        validated.append({
            "conclusion": conclusion,
            "reasoning": reasoning,
            "tags": safe_tags,
        })
    return validated


def _build_dream_plan(
    parents: List[MemoryTrace],
    insights: list[dict],
    consolidation_id: str,
    policy: tuple[str, str],
) -> dict:
    parent_ids = [str(parent.id) for parent in parents]
    planned_at = time.time()
    if (
        isinstance(planned_at, bool)
        or not isinstance(planned_at, (int, float))
        or not math.isfinite(float(planned_at))
    ):
        raise _DreamPlanError("dream plan timestamp is invalid")
    planned_at = float(planned_at)
    derived = []
    for item_index, item in enumerate(insights):
        conclusion = item["conclusion"]
        reasoning = item["reasoning"]
        safe_tags = item["tags"]
        derived.append(MemoryTrace(
            id=str(uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"{consolidation_id}:semantic:{item_index}",
            )),
            content=(
                f"Suy luận đúc kết ({', '.join(safe_tags[:3])}): "
                f"{conclusion} (Lý do: {reasoning})"
            ),
            type=MemoryType.SEMANTIC,
            valence=0.0,
            arousal=0.5,
            importance=1.0,
            created_at=planned_at,
            last_recalled=planned_at,
            last_decayed_at=planned_at,
            is_flashbulb=True,
            consolidation_id=consolidation_id,
            consolidation_parent_ids=list(parent_ids),
            scope=policy[0],
            privacy=policy[1],
            origin_kind="consolidation",
            origin_source="sleep",
            source_event_id=None,
            provenance_parent_ids=list(parent_ids),
        ))
        if len(conclusion) > 10:
            derived.append(MemoryTrace(
                id=str(uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"{consolidation_id}:core:{item_index}",
                )),
                content=f"Niềm tin cốt lõi (Belief): {conclusion}",
                type=MemoryType.CORE,
                valence=0.5,
                arousal=0.2,
                importance=1.0,
                created_at=planned_at,
                last_recalled=planned_at,
                last_decayed_at=planned_at,
                is_flashbulb=True,
                consolidation_id=consolidation_id,
                consolidation_parent_ids=list(parent_ids),
                scope=policy[0],
                privacy=policy[1],
                origin_kind="consolidation",
                origin_source="sleep",
                source_event_id=None,
                provenance_parent_ids=list(parent_ids),
            ))
    expected_count = len(derived)
    if not 1 <= expected_count <= 2 * _MAX_DREAM_INSIGHTS:
        raise _DreamPlanError("dream plan child count is invalid")
    for trace in derived:
        trace.consolidation_expected_derived_count = expected_count
    return {
        "children": [_dream_trace_to_spec(trace) for trace in derived],
        "consolidated_at": planned_at,
        "consolidation_id": consolidation_id,
        "parent_fingerprints": [
            {"id": str(parent.id), "sha256": _dream_parent_fingerprint(parent)}
            for parent in parents
        ],
        "parent_ids": parent_ids,
        "policy": {"privacy": policy[1], "scope": policy[0]},
        "version": _DREAM_PLAN_VERSION,
    }


def _decode_dream_plan(
    record: OperationRecord,
) -> tuple[list, list, tuple[str, str], str, float, list[MemoryTrace]]:
    plan = record.plan
    if (
        record.op_type != _DREAM_OPERATION_TYPE
        or type(plan) is not dict
        or set(plan) != {
            "children",
            "consolidated_at",
            "consolidation_id",
            "parent_fingerprints",
            "parent_ids",
            "policy",
            "version",
        }
        or type(plan.get("version")) is not int
        or plan.get("version") != _DREAM_PLAN_VERSION
    ):
        raise _DreamPlanError("dream operation envelope is invalid")
    parent_ids = plan.get("parent_ids")
    fingerprints = plan.get("parent_fingerprints")
    policy_data = plan.get("policy")
    consolidated_at = plan.get("consolidated_at")
    consolidation_id = plan.get("consolidation_id")
    children_data = plan.get("children")
    if (
        type(parent_ids) is not list
        or not 3 <= len(parent_ids) <= 15
        or any(type(parent_id) is not str or not parent_id for parent_id in parent_ids)
        or len(set(parent_ids)) != len(parent_ids)
        or type(fingerprints) is not list
        or len(fingerprints) != len(parent_ids)
        or type(policy_data) is not dict
        or set(policy_data) != {"privacy", "scope"}
        or isinstance(consolidated_at, bool)
        or not isinstance(consolidated_at, (int, float))
        or not math.isfinite(float(consolidated_at))
        or type(consolidation_id) is not str
        or type(children_data) is not list
        or not 1 <= len(children_data) <= 2 * _MAX_DREAM_INSIGHTS
    ):
        raise _DreamPlanError("dream operation plan is invalid")
    policy = (policy_data.get("scope"), policy_data.get("privacy"))
    if (
        policy[0] not in {MemoryScope.AGENT.value, MemoryScope.OWNER.value}
        or policy[1] != MemoryPrivacy.STANDARD.value
        or consolidation_id != _dream_consolidation_id(parent_ids)
        or record.op_id != _dream_operation_id(consolidation_id)
    ):
        raise _DreamPlanError("dream operation identity is invalid")
    for parent_id, fingerprint in zip(parent_ids, fingerprints):
        if (
            type(fingerprint) is not dict
            or set(fingerprint) != {"id", "sha256"}
            or fingerprint.get("id") != parent_id
            or type(fingerprint.get("sha256")) is not str
            or len(fingerprint["sha256"]) != 64
            or any(char not in "0123456789abcdef" for char in fingerprint["sha256"])
        ):
            raise _DreamPlanError("dream parent fingerprint is invalid")
    expected_count = len(children_data)
    children = [
        _dream_trace_from_spec(
            item,
            consolidation_id=consolidation_id,
            parent_ids=parent_ids,
            policy=policy,
            expected_count=expected_count,
        )
        for item in children_data
    ]
    if (
        len({str(child.id) for child in children}) != expected_count
        or not _valid_consolidation_child_set(
            children,
            consolidation_id,
            expected_count,
        )
    ):
        raise _DreamPlanError("dream child set is invalid")
    if any(float(child.created_at) != float(consolidated_at) for child in children):
        raise _DreamPlanError("dream marker timestamp is not canonical")
    return (
        parent_ids,
        fingerprints,
        policy,
        consolidation_id,
        float(consolidated_at),
        children,
    )


def _reappraisal_marker(attempt_id: object) -> str:
    if type(attempt_id) is not str:
        raise _DreamPlanError("reappraisal attempt ID is invalid")
    try:
        parsed = uuid.UUID(attempt_id)
    except (ValueError, AttributeError) as exc:
        raise _DreamPlanError("reappraisal attempt ID is invalid") from exc
    if str(parsed) != attempt_id:
        raise _DreamPlanError("reappraisal attempt ID is not canonical")
    return f"[ToReevaluate:{attempt_id}]"


def _reappraisal_attempt_from_marker(marker: object) -> str | None:
    if type(marker) is not str:
        return None
    match = _REAPPRAISAL_MARKER_RE.fullmatch(marker)
    if match is None:
        return None
    attempt_id = match.group(1)
    try:
        return attempt_id if _reappraisal_marker(attempt_id) == marker else None
    except _DreamPlanError:
        return None


def _reappraisal_operation_id(attempt_id: str) -> str:
    _reappraisal_marker(attempt_id)
    return f"reappraisal:{attempt_id}"


def _reappraisal_child_id(attempt_id: str) -> str:
    _reappraisal_marker(attempt_id)
    return str(uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"aura:reappraisal-child:{attempt_id}",
    ))


def _reappraisal_rekeyed_attempt_id(
    attempt_id: str,
    parent_id: str,
) -> str:
    _reappraisal_marker(attempt_id)
    if (
        type(parent_id) is not str
        or not parent_id
        or len(parent_id) > 512
    ):
        raise _DreamPlanError("reappraisal parent identity is invalid")
    try:
        parent_id.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise _DreamPlanError(
            "reappraisal parent identity is invalid"
        ) from exc
    if "\x00" in parent_id:
        raise _DreamPlanError("reappraisal parent identity is invalid")
    return str(uuid.uuid5(
        uuid.NAMESPACE_URL,
        "aura:reappraisal-rekey:"
        + _canonical_json({
            "attempt_id": attempt_id,
            "parent_id": parent_id,
        }),
    ))


def _legacy_reappraisal_child_id(parent_id: str) -> str:
    return str(uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"aura:reappraisal:{parent_id}",
    ))


def _remove_one_legacy_reappraisal_marker(
    text: object,
) -> tuple[str, str | None]:
    """Remove only one marker at a location written by the legacy runtime."""

    if type(text) is not str:
        return str(text), None
    marker_start = None
    if text.startswith(_REAPPRAISAL_LEGACY_MARKER):
        marker_start = 0
    else:
        user_prefix = "User: " + _REAPPRAISAL_LEGACY_MARKER
        user_offset = text.find(user_prefix)
        if user_offset >= 0:
            marker_start = user_offset + len("User: ")
    if marker_start is None:
        return text, None
    marker_end = marker_start + len(_REAPPRAISAL_LEGACY_MARKER)
    suffix_start = marker_end + (1 if text[marker_end:marker_end + 1] == " " else 0)
    try:
        locator_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    except UnicodeEncodeError:
        return text, None
    return (
        text[:marker_start] + text[suffix_start:],
        f"{marker_start}:{locator_hash}",
    )


def _bounded_reappraisal_text(
    value: object,
    *,
    field: str,
    max_chars: int,
) -> str:
    if type(value) is not str:
        raise _DreamPlanError(f"reappraisal {field} is not text")
    normalized = value.strip()
    if not normalized or len(normalized) > max_chars:
        raise _DreamPlanError(f"reappraisal {field} is not bounded text")
    try:
        normalized.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise _DreamPlanError(
            f"reappraisal {field} is not valid UTF-8"
        ) from exc
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise _DreamPlanError(
            f"reappraisal {field} contains control characters"
        )
    return normalized


def _reappraisal_parent_fingerprint(trace: MemoryTrace) -> str:
    record_id = getattr(trace, "id", None)
    content = getattr(trace, "content", None)
    if (
        type(record_id) is not str
        or not record_id
        or len(record_id) > 512
        or type(content) is not str
        or len(content) > _MAX_REAPPRAISAL_PARENT_CONTENT_CHARS
    ):
        raise _DreamPlanError("reappraisal parent identity is invalid")
    try:
        record_id.encode("utf-8", errors="strict")
        content.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise _DreamPlanError(
            "reappraisal parent text is not valid UTF-8"
        ) from exc
    if "\x00" in content:
        raise _DreamPlanError("reappraisal parent content contains a null")
    try:
        memory_type = MemoryType(getattr(trace, "type", None)).value
    except (TypeError, ValueError) as exc:
        raise _DreamPlanError("reappraisal parent type is invalid") from exc
    created_at = getattr(trace, "created_at", None)
    if (
        isinstance(created_at, bool)
        or not isinstance(created_at, (int, float))
        or not math.isfinite(float(created_at))
    ):
        raise _DreamPlanError("reappraisal parent timestamp is invalid")
    policy = _memory_policy(trace)
    provenance = getattr(trace, "provenance_parent_ids", None)
    origin_kind = getattr(trace, "origin_kind", None)
    origin_source = getattr(trace, "origin_source", None)
    source_event_id = getattr(trace, "source_event_id", None)
    if (
        policy is None
        or type(provenance) is not list
        or any(type(parent_id) is not str or not parent_id for parent_id in provenance)
        or len(set(provenance)) != len(provenance)
        or type(origin_kind) is not str
        or not origin_kind.strip()
        or type(origin_source) is not str
        or not origin_source.strip()
        or (
            source_event_id is not None
            and (type(source_event_id) is not str or not source_event_id.strip())
        )
    ):
        raise _DreamPlanError("reappraisal parent provenance is invalid")
    payload = {
        "content": content,
        "created_at": float(created_at),
        "id": record_id,
        "origin_kind": origin_kind,
        "origin_source": origin_source,
        "privacy": policy[1],
        "provenance_parent_ids": list(provenance),
        "scope": policy[0],
        "source_event_id": source_event_id,
        "type": memory_type,
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _parse_reappraisal_decision(raw_response: object) -> dict:
    if (
        type(raw_response) is not str
        or len(raw_response) > _MAX_REAPPRAISAL_RESPONSE_CHARS
    ):
        raise _DreamPlanError("reappraisal response is not bounded text")
    json_text = raw_response.strip()
    if json_text.startswith("```json") and json_text.endswith("```"):
        json_text = json_text[len("```json"):-len("```")].strip()
    elif json_text.startswith("```") and json_text.endswith("```"):
        json_text = json_text[len("```"):-len("```")].strip()
    try:
        payload = json.loads(
            json_text,
            object_pairs_hook=_dream_object_without_duplicates,
            parse_constant=_dream_reject_non_finite,
        )
    except (json.JSONDecodeError, TypeError, ValueError, RecursionError) as exc:
        raise _DreamPlanError("reappraisal response is invalid JSON") from exc
    if (
        type(payload) is not dict
        or set(payload) != {"action", "reasoning", "new_belief"}
    ):
        raise _DreamPlanError("reappraisal response shape is invalid")
    action = payload["action"]
    if type(action) is not str or action not in {"EVOLVE", "SOFTEN", "REJECT"}:
        raise _DreamPlanError("reappraisal action is invalid")
    reasoning = _bounded_reappraisal_text(
        payload["reasoning"],
        field="reasoning",
        max_chars=_MAX_REAPPRAISAL_REASONING_CHARS,
    )
    new_belief = payload["new_belief"]
    if action == "EVOLVE":
        new_belief = _bounded_reappraisal_text(
            new_belief,
            field="new belief",
            max_chars=_MAX_REAPPRAISAL_BELIEF_CHARS,
        )
    elif type(new_belief) is not str or new_belief.strip():
        raise _DreamPlanError(
            "non-EVOLVE reappraisal must not contain a new belief"
        )
    else:
        new_belief = ""
    return {
        "action": action,
        "new_belief": new_belief,
        "reasoning": reasoning,
    }


def _build_reappraisal_plan(
    parent: MemoryTrace,
    attempt_id: str,
    decision: dict,
) -> dict:
    marker = _reappraisal_marker(attempt_id)
    policy = _memory_policy(parent)
    if policy is None:
        raise _DreamPlanError("reappraisal parent policy is invalid")
    action = decision["action"]
    child_spec = None
    target_valence = None
    if action == "EVOLVE":
        planned_at = time.time()
        if (
            isinstance(planned_at, bool)
            or not isinstance(planned_at, (int, float))
            or not math.isfinite(float(planned_at))
        ):
            raise _DreamPlanError("reappraisal timestamp is invalid")
        child = MemoryTrace(
            id=_reappraisal_child_id(attempt_id),
            content=_REAPPRAISAL_CHILD_PREFIX + decision["new_belief"],
            type=MemoryType.CORE,
            valence=0.5,
            arousal=0.3,
            importance=1.0,
            created_at=float(planned_at),
            last_recalled=float(planned_at),
            last_decayed_at=float(planned_at),
            is_flashbulb=True,
            scope=policy[0],
            privacy=policy[1],
            origin_kind="reappraisal",
            origin_source="sleep",
            source_event_id=None,
            provenance_parent_ids=[str(parent.id)],
        )
        child_spec = _dream_trace_to_spec(child)
    elif action == "SOFTEN":
        target_valence = 0.0
    else:
        target_valence = -0.5
    return {
        "action": action,
        "attempt_id": attempt_id,
        "child": child_spec,
        "marker": marker,
        "parent_fingerprint": _reappraisal_parent_fingerprint(parent),
        "parent_id": str(parent.id),
        "policy": {"privacy": policy[1], "scope": policy[0]},
        "reasoning": decision["reasoning"],
        "target_valence": target_valence,
        "version": _REAPPRAISAL_PLAN_VERSION,
    }


def _decode_reappraisal_plan(
    record: OperationRecord,
) -> tuple[str, str, str, tuple[str, str], str, float | None, MemoryTrace | None]:
    plan = record.plan
    required = {
        "action",
        "attempt_id",
        "child",
        "marker",
        "parent_fingerprint",
        "parent_id",
        "policy",
        "reasoning",
        "target_valence",
        "version",
    }
    if (
        record.op_type != _REAPPRAISAL_OPERATION_TYPE
        or type(plan) is not dict
        or set(plan) != required
        or type(plan.get("version")) is not int
        or plan.get("version") != _REAPPRAISAL_PLAN_VERSION
    ):
        raise _DreamPlanError("reappraisal operation envelope is invalid")
    attempt_id = plan.get("attempt_id")
    marker = _reappraisal_marker(attempt_id)
    parent_id = plan.get("parent_id")
    fingerprint = plan.get("parent_fingerprint")
    policy_data = plan.get("policy")
    action = plan.get("action")
    reasoning = _bounded_reappraisal_text(
        plan.get("reasoning"),
        field="reasoning",
        max_chars=_MAX_REAPPRAISAL_REASONING_CHARS,
    )
    del reasoning
    if (
        plan.get("marker") != marker
        or record.op_id != _reappraisal_operation_id(attempt_id)
        or type(parent_id) is not str
        or not parent_id
        or len(parent_id) > 512
        or type(fingerprint) is not str
        or len(fingerprint) != 64
        or any(character not in "0123456789abcdef" for character in fingerprint)
        or type(policy_data) is not dict
        or set(policy_data) != {"privacy", "scope"}
        or type(action) is not str
        or action not in {"EVOLVE", "SOFTEN", "REJECT"}
    ):
        raise _DreamPlanError("reappraisal operation identity is invalid")
    policy = (policy_data.get("scope"), policy_data.get("privacy"))
    if (
        policy[0] not in {MemoryScope.AGENT.value, MemoryScope.OWNER.value}
        or policy[1] != MemoryPrivacy.STANDARD.value
    ):
        raise _DreamPlanError("reappraisal operation policy is invalid")

    child_data = plan.get("child")
    target_valence = plan.get("target_valence")
    child = None
    if action == "EVOLVE":
        if target_valence is not None or type(child_data) is not dict:
            raise _DreamPlanError("EVOLVE reappraisal plan is invalid")
        if set(child_data) != set(MemoryTrace.__dataclass_fields__):
            raise _DreamPlanError("reappraisal child shape is invalid")
        try:
            child = MemoryTrace(**copy.deepcopy(child_data))
            exact_child = (
                _canonical_json(_dream_trace_to_spec(child))
                == _canonical_json(child_data)
            )
        except (TypeError, ValueError, OverflowError) as exc:
            raise _DreamPlanError("reappraisal child cannot be decoded") from exc
        child_content = str(child.content)
        child_belief = child_content[len(_REAPPRAISAL_CHILD_PREFIX):]
        try:
            canonical_child_belief = _bounded_reappraisal_text(
                child_belief,
                field="new belief",
                max_chars=_MAX_REAPPRAISAL_BELIEF_CHARS,
            )
        except _DreamPlanError:
            canonical_child_belief = None
        if (
            not exact_child
            or str(child.id) != _reappraisal_child_id(attempt_id)
            or not _has_memory_type(child, MemoryType.CORE)
            or not child_content.startswith(_REAPPRAISAL_CHILD_PREFIX)
            or canonical_child_belief is None
            or child_content
            != _REAPPRAISAL_CHILD_PREFIX + canonical_child_belief
            or _memory_policy(child) != policy
            or child.origin_kind != "reappraisal"
            or child.origin_source != "sleep"
            or child.source_event_id is not None
            or list(child.provenance_parent_ids) != [parent_id]
            or child.consolidation_id
            or child.consolidation_parent_ids
            or child.consolidation_expected_derived_count != 0
            or child.is_consolidated_source
            or child.consolidated_at is not None
            or not child.is_flashbulb
        ):
            raise _DreamPlanError("reappraisal child authority is invalid")
    else:
        expected_target = 0.0 if action == "SOFTEN" else -0.5
        if (
            child_data is not None
            or isinstance(target_valence, bool)
            or not isinstance(target_valence, (int, float))
            or not math.isfinite(float(target_valence))
            or float(target_valence) != expected_target
        ):
            raise _DreamPlanError("reappraisal valence plan is invalid")
        target_valence = expected_target
    return (
        parent_id,
        attempt_id,
        marker,
        policy,
        fingerprint,
        target_valence,
        child,
    )


def _is_episodic_source(trace: MemoryTrace) -> bool:
    try:
        return MemoryType(trace.type) == MemoryType.EPISODIC
    except (TypeError, ValueError):
        return False


def _has_memory_type(trace: MemoryTrace, expected: MemoryType) -> bool:
    try:
        return MemoryType(trace.type) == expected
    except (TypeError, ValueError):
        return False


def _is_belief_source(trace: MemoryTrace) -> bool:
    return (
        (_has_memory_type(trace, MemoryType.CORE)
         or _has_memory_type(trace, MemoryType.SEMANTIC))
        and "Belief" in str(getattr(trace, "content", ""))
        and not str(
            getattr(trace, "consolidation_id", "") or ""
        ).startswith("belief-delete:")
        and _memory_policy(trace) is not None
    )


def _is_canonical_belief_merge_child(
    trace: MemoryTrace,
    parent_ids: List[str],
    *,
    policy: tuple[str, str] | None = None,
) -> bool:
    content = str(getattr(trace, "content", ""))
    if not content.startswith(_BELIEF_CONTENT_PREFIX):
        return False
    new_content = content[len(_BELIEF_CONTENT_PREFIX):].strip()
    if not new_content or content != _BELIEF_CONTENT_PREFIX + new_content:
        return False
    expected_id = _belief_merge_child_id(parent_ids, new_content)
    trace_policy = _memory_policy(trace)
    return (
        str(trace.id) == expected_id
        and trace.consolidation_id == f"belief-merge:{expected_id}"
        and _has_memory_type(trace, MemoryType.CORE)
        and list(trace.consolidation_parent_ids) == parent_ids
        and list(trace.provenance_parent_ids) == parent_ids
        and trace.origin_kind == "belief_evolution"
        and trace.origin_source == "sleep"
        and trace_policy is not None
        and (policy is None or trace_policy == policy)
    )


def _belief_merge_content_from_child(trace: MemoryTrace) -> str | None:
    content = str(getattr(trace, "content", ""))
    if not content.startswith(_BELIEF_CONTENT_PREFIX):
        return None
    new_content = content[len(_BELIEF_CONTENT_PREFIX):].strip()
    if not new_content or content != _BELIEF_CONTENT_PREFIX + new_content:
        return None
    return new_content


def _belief_merge_content_from_intent(trace: MemoryTrace) -> str | None:
    content = str(getattr(trace, "content", ""))
    if not content.startswith(_BELIEF_MERGE_INTENT_PREFIX):
        return None
    new_content = content[len(_BELIEF_MERGE_INTENT_PREFIX):].strip()
    if not new_content or content != _BELIEF_MERGE_INTENT_PREFIX + new_content:
        return None
    return new_content


def _build_belief_merge_child(
    parent_ids: List[str],
    policy: tuple[str, str],
    new_content: str,
) -> MemoryTrace:
    merge_id = _belief_merge_child_id(parent_ids, new_content)
    return MemoryTrace(
        id=merge_id,
        content=_BELIEF_CONTENT_PREFIX + new_content,
        type=MemoryType.CORE,
        valence=0.5,
        arousal=0.2,
        importance=1.0,
        is_flashbulb=True,
        consolidation_id=f"belief-merge:{merge_id}",
        consolidation_parent_ids=parent_ids,
        consolidation_expected_derived_count=2,
        scope=policy[0],
        privacy=policy[1],
        origin_kind="belief_evolution",
        origin_source="sleep",
        provenance_parent_ids=parent_ids,
    )


def _build_belief_delete_intent(
    parent_ids: List[str],
    policy: tuple[str, str],
    *,
    merge_content: str | None = None,
) -> MemoryTrace:
    intent_id = _belief_delete_intent_id(parent_ids)
    return MemoryTrace(
        id=intent_id,
        content=(
            _BELIEF_DELETE_INTENT_CONTENT
            if merge_content is None
            else _BELIEF_MERGE_INTENT_PREFIX + merge_content
        ),
        type=MemoryType.SEMANTIC,
        valence=0.0,
        arousal=0.0,
        importance=0.0,
        strength=0.0,
        consolidation_id=f"belief-delete:{intent_id}",
        consolidation_parent_ids=parent_ids,
        consolidation_expected_derived_count=(
            1 if merge_content is None else 2
        ),
        scope=policy[0],
        privacy=policy[1],
        origin_kind="belief_evolution",
        origin_source="sleep",
        provenance_parent_ids=parent_ids,
    )


def _memory_temporal_order(trace: MemoryTrace) -> tuple[float, str]:
    created_at = getattr(trace, "created_at", 0.0)
    try:
        created_at = float(created_at)
    except (TypeError, ValueError, OverflowError):
        created_at = 0.0
    if not math.isfinite(created_at):
        created_at = 0.0
    return created_at, str(trace.id)


class MemoryOperationsController:
    # Phase 14: Sliding Context Window cap
    STM_MAX_ENTRIES = 15

    def __init__(self, engine):
        self.engine = engine
        self.last_sleep_outcome = SleepOutcome(sleep_committed=False)
        from core.engine.integrity_filter import IntegrityFilter
        self.integrity_filter = IntegrityFilter(engine)
        self.slm_trainer = None
        if getattr(Config, "SLM_TRAINING_ENABLED", False):
            try:
                from core.engine.slm_trainer import SLMTrainer
                self.slm_trainer = SLMTrainer(engine)
            except Exception:
                self.slm_trainer = None

    def _apply_fog_masking(self, content: str) -> str:
        """[Phase 21] Che mờ các chi tiết cụ thể nếu Aura đang mệt mỏi hoặc stress."""
        import re
        fatigue = getattr(self.engine.ego, 'fatigue', 0.0)
        stress = getattr(self.engine.ego, 'stress', 0.0)
        
        # Chỉ mask nếu mệt mỏi hoặc stress cao
        if fatigue > 0.6 or stress > 0.7:
            # Mask số (số điện thoại, mã số, số lượng cụ thể)
            content = re.sub(r'\b\d{3,}\b', '[dữ liệu mờ nhạt]', content)
            # Mask thời gian (HH:MM)
            content = re.sub(r'\b\d{1,2}:\d{2}\b', '[thời gian không rõ]', content)
            # Mask ngày tháng (DD/MM/YYYY)
            content = re.sub(r'\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b', '[ngày tháng bị nhòe]', content)
            
        # Tên riêng không còn bị đoán bằng chữ hoa (sai với tiếng Việt); ký ức
        # mờ được rút gọn thành ý chính ở faint_gist() thay vào đó.
        return content

    # Below this strength a memory is only half there: the gist and the
    # feeling remain, names and details are gone ("nhớ mang máng").
    FAINT_STRENGTH = 0.25
    FAINT_STRENGTH_WHEN_TIRED = 0.5
    _GIST_CHARS = 70

    def is_faint(self, memory) -> bool:
        if getattr(memory, "is_flashbulb", False):
            return False  # khắc sâu, không bao giờ mờ
        strength = float(getattr(memory, "strength", 1.0) or 0.0)
        tired = getattr(self.engine.ego, "fatigue", 0.0) > 0.75
        limit = self.FAINT_STRENGTH_WHEN_TIRED if tired else self.FAINT_STRENGTH
        return strength < limit

    @classmethod
    def faint_gist(cls, content: str) -> str:
        """First clause only, without the specifics a fading memory loses."""
        import re

        first = re.split(r"(?<=[.!?;])\s|\n", str(content).strip(), maxsplit=1)[0]
        first = re.sub(r"\d", "…", first)
        if len(first) > cls._GIST_CHARS:
            first = first[: cls._GIST_CHARS].rsplit(" ", 1)[0] + "…"
        return first

    def load_short_term_memory(self):
        """Khoi phuc bo nho ngan han tu o cung neu thoi gian chua troi qua qua lau (3 tieng)"""
        from config import Config
        path = Config.STM_FILE
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    last_updated = data.get("timestamp", 0)
                    saved_buffer = data.get("buffer", [])
                    
                    if time.time() - last_updated < 3 * 3600:
                        # Chi phuc hoi toi da STM_MAX_ENTRIES cuoi cung
                        with self.engine.stm_lock:
                            self.engine.short_term_buffer = saved_buffer[-self.STM_MAX_ENTRIES:]
                            count = len(self.engine.short_term_buffer)
                        print(f"{Fore.LIGHTBLACK_EX}[WORKING MEMORY]: Phuc hoi {count} ky uc ngan han tu phien truoc.{Style.RESET_ALL}")
                    else:
                        print(f"{Fore.LIGHTBLACK_EX}[WORKING MEMORY]: Ky uc ngan han da qua han 3 tieng. Xoa sach.{Style.RESET_ALL}")
            except Exception as e:
                print(f"{Fore.RED}Loi nap bo nho ngan han: {e}{Style.RESET_ALL}")

    def save_short_term_memory(self):
        """Luu de mang tri nho ngan han xuong o cung (voi cap STM_MAX_ENTRIES)"""
        from core.utils import atomic_write_json
        from config import Config
        path = Config.STM_FILE
        try:
            with self.engine.stm_lock:
                # Phase 14: Cap truoc khi luu — tranh file phong to vo han
                if len(self.engine.short_term_buffer) > self.STM_MAX_ENTRIES:
                    self.engine.short_term_buffer = self.engine.short_term_buffer[-self.STM_MAX_ENTRIES:]
                buffer_copy = list(self.engine.short_term_buffer)
            data = {
                "timestamp": time.time(),
                "buffer": buffer_copy
            }
            atomic_write_json(path, data)
        except Exception as e:
            print(f"{Fore.RED}Loi luu bo nho ngan han: {e}{Style.RESET_ALL}")

    def build_recall_plan(
        self,
        query: str,
        *,
        now: float,
        force_local: bool = False,
    ) -> RecallPlan:
        """Read and rank memories without mutating runtime or persistent state."""
        # The current embedder is cloud-backed. A hard-local request must stop
        # before any memory read can invoke it.
        if force_local:
            return RecallPlan(
                hits=(),
                mood=0.0,
                dynamic_top_k=0,
                return_limit=0,
                throttle_level="",
                chronological_error_type=None,
                force_local=True,
            )

        base_top_k = 10
        fatigue = getattr(self.engine.ego, "fatigue", 0.0)
        stress = getattr(self.engine.ego, "stress", 0.0)
        mood = getattr(self.engine.ego, "mood", 0.0)
        stress_penalty = int(stress * 6)
        fatigue_penalty = int(fatigue * 4)
        dynamic_top_k = max(1, base_top_k - stress_penalty - fatigue_penalty)
        throttle_level = ""
        if dynamic_top_k < 5:
            throttle_level = "deep"
        elif dynamic_top_k < base_top_k:
            throttle_level = "reduced"

        results = self.engine.memory.search_memories(query, top_k=dynamic_top_k)
        candidates: list[MemoryHit] = []
        for raw_score, memory in results:
            if memory.strength < 0.1:
                continue
            try:
                score = float(raw_score)
            except (TypeError, ValueError, OverflowError):
                continue
            if not math.isfinite(score):
                continue
            mood_bias = 0.0
            if mood < -0.3 and memory.valence < -0.2:
                mood_bias = 0.3
            elif mood > 0.3 and memory.valence > 0.2:
                mood_bias = 0.3
            elif mood < -0.3 and memory.valence > 0.3:
                mood_bias = -0.2
            final_score = (
                score
                * memory.strength
                * (1 + memory.arousal)
                * (1 + mood_bias)
            )
            if final_score > 0.35:
                candidates.append(MemoryHit(final_score, memory))

        time_kws = [
            'h\u00f4m nay', 'h\u00f4m qua', 'v\u1eeba n\u00e3y',
            'tr\u01b0\u1edbc \u0111\u00f3', 'm\u1edbi \u0111\u00e2y', 's\u00e1ng nay',
            'chi\u1ec1u nay', 't\u1ed1i qua', 'g\u1ea7n \u0111\u00e2y', 'l\u00fac n\u00e3y',
        ]
        chronological_error_type = None
        if any(keyword in query.lower() for keyword in time_kws):
            try:
                chrono_results = self.engine.memory.chronological_recall(
                    now - 86400 * 3,
                    now,
                    limit=min(5, dynamic_top_k),
                )
                candidate_ids = {str(hit.memory.id) for hit in candidates}
                for memory in chrono_results:
                    memory_id = str(memory.id)
                    if memory.strength >= 0.1 and memory_id not in candidate_ids:
                        candidates.append(MemoryHit(1.0, memory))
                        candidate_ids.add(memory_id)
            except Exception as exc:
                chronological_error_type = type(exc).__name__

        # Exact score ties are resolved by stable record id, independent of DB
        # response ordering.
        candidates.sort(key=lambda hit: (-hit.score, str(hit.memory.id)))
        return_limit = max(
            1,
            4 - (stress_penalty // 2) - (fatigue_penalty // 2),
        )
        selected = list(candidates[:return_limit])

        if selected:
            anchor_memory = selected[0].memory
            associative_results = self.engine.memory.search_memories(
                anchor_memory.content,
                top_k=5,
            )
            selected_ids = {str(hit.memory.id) for hit in selected}
            associative_candidates: list[MemoryHit] = []
            for raw_score, memory in associative_results:
                memory_id = str(memory.id)
                if (
                    memory_id == str(anchor_memory.id)
                    or memory_id in selected_ids
                    or memory.strength <= 0.4
                ):
                    continue
                try:
                    score = float(raw_score)
                except (TypeError, ValueError, OverflowError):
                    continue
                if math.isfinite(score):
                    associative_candidates.append(
                        MemoryHit(score, memory, is_associative=True)
                    )
            associative_candidates.sort(
                key=lambda hit: (-hit.score, str(hit.memory.id))
            )
            if associative_candidates:
                selected.append(associative_candidates[0])

        return RecallPlan(
            hits=tuple(selected),
            mood=mood,
            dynamic_top_k=dynamic_top_k,
            return_limit=return_limit,
            throttle_level=throttle_level,
            chronological_error_type=chronological_error_type,
            force_local=False,
        )

    def apply_recall_effects(self, plan: RecallPlan) -> List[MemoryTrace]:
        """Apply reconsolidation and persistence for an explicit recall plan."""
        if plan.throttle_level == "deep":
            print(
                f"{Fore.RED}🌫️ [DEEP BRAIN FOG]: Trí nhớ bị bóp nghẹt "
                f"nghiêm trọng ({plan.dynamic_top_k}/10 nodes).{Style.RESET_ALL}"
            )
        elif plan.throttle_level == "reduced":
            print(
                f"{Fore.LIGHTBLACK_EX}📉 [COGNITIVE THROTTLING]: Khả năng tập "
                f"trung giảm ({plan.dynamic_top_k}/10 nodes).{Style.RESET_ALL}"
            )
        if plan.chronological_error_type:
            print(
                f"{Fore.RED}\u26a0\ufe0f L\u1ed7i tr\u1ef3 xu\u1ea5t th\u1eddi gian "
                f"({plan.chronological_error_type}).{Style.RESET_ALL}"
            )

        recalled = [hit.memory for hit in plan.hits]
        for hit in plan.hits:
            memory = hit.memory
            # Agent knowledge is readable during an owner interaction, but the
            # request must not reconsolidate or rewrite that read-only record.
            if not _memory_is_writable(memory):
                continue
            previous_state = copy.deepcopy(memory.__dict__)
            needs_rewrite = memory.reconsolidate(
                plan.mood,
                is_associative=hit.is_associative,
            )
            content_was_upserted = False

            if needs_rewrite:
                try:
                    from core.prompts import get_reconsolidate_rewrite_prompt
                    prompt = get_reconsolidate_rewrite_prompt(
                        memory.content,
                        plan.mood,
                    )
                    new_content, _ = self.engine.llm.generate_text(
                        prompt,
                        temperature=0.7,
                        force_local=plan.force_local,
                    )
                    if (
                        new_content
                        and len(new_content) > 10
                        and new_content != memory.content
                    ):
                        print(f"{Fore.LIGHTRED_EX}🌀 [FALSE MEMORY]: Ký ức bị bóp méo do tâm trạng:\n   - Cũ: {memory.content}\n   - Mới: {new_content}{Style.RESET_ALL}")
                        memory.content = new_content
                        try:
                            self.engine.memory.upsert_memory(memory)
                        except Exception:
                            _restore_trace_state(memory, previous_state)
                            raise
                        content_was_upserted = True
                except MemoryStoreError:
                    raise
                except Exception as exc:
                    print(
                        f"{Fore.RED}Lỗi True False Memories: "
                        f"{type(exc).__name__}{Style.RESET_ALL}"
                    )

            if not content_was_upserted:
                try:
                    self.engine.memory.update_memory(memory)
                except Exception:
                    _restore_trace_state(memory, previous_state)
                    raise
        return recalled

    def recall(self, query: str, *, force_local: bool = False) -> List[MemoryTrace]:
        """Backward-compatible recall wrapper: plan first, then apply effects."""
        plan = self.build_recall_plan(
            query,
            now=0.0 if force_local else time.time(),
            force_local=force_local,
        )
        return self.apply_recall_effects(plan)

    def apply_semantic_drift(
        self,
        memory: MemoryTrace,
        *,
        elapsed_days: float = 1.0,
    ):
        if memory.is_flashbulb or memory.type in [MemoryType.CORE, MemoryType.SEMANTIC] or memory.recall_count < 2:
            return False
        try:
            elapsed_days = max(0.0, float(elapsed_days))
        except (TypeError, ValueError, OverflowError):
            elapsed_days = 0.0
        base_chance = max(0.0, min(1.0, float(Config.SEMANTIC_DRIFT_CHANCE)))
        elapsed_chance = 1.0 - ((1.0 - base_chance) ** elapsed_days)
        if random.random() > elapsed_chance:
            return False
        prompt = get_semantic_drift_prompt(memory.content)
        new_content, _ = self.engine.llm.generate_text(prompt, temperature=0.8)
        if new_content and len(new_content) > 10 and new_content != memory.content:
            print(f"{Fore.LIGHTRED_EX}🌀 [SEMANTIC DRIFT]: Ký ức méo mó theo thời gian:\n   - Cũ: {memory.content}\n   - Mới: {new_content}{Style.RESET_ALL}")
            previous_content = memory.content
            memory.content = new_content
            try:
                self.engine.memory.upsert_memory(memory)
            except Exception:
                memory.content = previous_content
                raise
            return True
        return False

    def update_or_add_memory(
        self, user_input: str, perception: dict, *, force_local: bool = False
    ):
        # Adding or searching vector memory invokes the cloud embedder today.
        # Keep hard-local inputs in local STM only rather than leaking them.
        if force_local:
            return
        # Read scope is wider than write scope: only a writable neighbour may
        # absorb an interaction. Otherwise an owner message could contaminate
        # agent-owned semantic/core memory.
        similar = self.engine.memory.search_memories(
            user_input,
            top_k=1,
            writable_only=True,
        )
        internal_thought = perception.get('internal_monologue', '...')
        new_valence, new_arousal, new_importance = perception.get('valence', 0.0), perception.get('arousal', 0.0), perception.get('importance', 0.5)
        
        # [Phase 5] White Bear Effect (Hiệu ứng Gấu Trắng)
        forget_keywords = ['quên đi', 'đừng nhớ', 'xóa ký ức', 'đừng nghĩ về', 'hãy quên', 'quên nó đi']
        is_forget_cmd = any(kw in user_input.lower() for kw in forget_keywords)
        
        if is_forget_cmd and similar and similar[0][0] > 0.6:
            target_mem = similar[0][1]
            if not getattr(target_mem, 'is_suppressed', False):
                previous_state = copy.deepcopy(target_mem.__dict__)
                target_mem.is_suppressed = True
                target_mem.arousal = max(target_mem.arousal, 0.9) # Tăng vọt arousal do lệnh cấm
                target_mem.strength = 1.0 # Kéo ký ức trở lại trạng thái cực kỳ tươi mới
                target_mem.importance = max(target_mem.importance, 0.8) # Bị dặn quên nên nó trở nên ám ảnh
                print(f"\n{Fore.RED}🐻‍❄️ [WHITE BEAR EFFECT]: Lệnh 'HÃY QUÊN' kích hoạt phản kháng ngược: Ký ức bị đè nén trở nên ám ảnh tột độ!{Style.RESET_ALL}")
                try:
                    self.engine.memory.update_memory(target_mem)
                except Exception:
                    _restore_trace_state(target_mem, previous_state)
                    raise
                
            # Đổi góc nhìn nội tâm khi bị ép quên
            internal_thought += " [AI càng bảo quên, mình lại càng không thể ngừng nghĩ về nó.]"
        
        # Phase 8 Idea 6.1: Sự Hoài Nghi Âm Thầm (Silent Skepticism)
        reappraisal_marker = None
        beliefs = self.engine.ego.get_active_beliefs(context_query=user_input)
        if beliefs:
            belief_str = ", ".join(beliefs)
            check_prompt = f"Câu nói sau của User có ĐI NGƯỢC LẠI, MÂU THUẪN HOÀN TOÀN, hay PHỦ NHẬN các niềm tin cốt lõi sau đây không? Niềm tin: {belief_str}. Câu nói: '{user_input}'. Chỉ trả lời YES hoặc NO."
            try:
                # [Phase 23] Neuro-Symbolic Integrity Filter (System 1)
                integrity_check = self.integrity_filter.check_contradiction(user_input, new_valence)
                if integrity_check["conflict"]:
                    print(f"{Fore.LIGHTYELLOW_EX}🧐 [HYBRID CONFLICT]: {integrity_check['reason']}{Style.RESET_ALL}")
                    internal_thought += f" [MÂU THUẪN: {integrity_check['reason']}]"
                    new_importance = min(1.0, new_importance * integrity_check["impact_multiplier"])
                    # Mâu thuẫn được ghi trong internal_thought; KHÔNG sửa lời
                    # User, nếu không ký ức sẽ lưu sai nguyên văn câu họ nói.
                
                ans, _ = self.engine.llm.generate_text(
                    check_prompt,
                    temperature=0.1,
                    force_local=force_local,
                    bio_throttle=False,
                ); ans = ans.strip().upper()
                # B15: dùng startswith thày 'in' — 'YES, because...' không bị detect lầm
                if ans.startswith("YES"):
                    print(f"{Fore.LIGHTYELLOW_EX}🧐 [COGNITIVE REAPPRAISAL]: Aura nhận thấy mâu thuẫn với niềm tin. Gắn thẻ chờ đánh giá lại...{Style.RESET_ALL}")
                    internal_thought += " [CÂN NHẮC: Thông tin này mâu thuẫn với niềm tin của mình. Cần suy nghĩ thêm khi ngủ.]"
                    reappraisal_marker = _reappraisal_marker(str(uuid.uuid4()))
                    new_valence = max(new_valence, -0.2) # Không còn bài xích cực đoan
            except Exception:
                pass
        
        is_flashbulb = new_arousal > 0.9 or new_importance > 0.9
        if is_flashbulb:
            print(f"{Fore.MAGENTA}⚡ [FLASHBULB MEMORY]: Sự kiện cực sốc/quan trọng được in hằn vĩnh viễn không phai!{Style.RESET_ALL}")

        if similar and similar[0][0] > 0.65:
            m = similar[0][1]
            previous_state = copy.deepcopy(m.__dict__)
            if not m.is_flashbulb and random.random() < 0.2:
                print(f"{Fore.LIGHTRED_EX}🎭 [CONFABULATION]: Ký ức cũ bị thao túng nhập nhằng với thông tin mới.{Style.RESET_ALL}")
                interaction_overlay = f"[Ám thị mới] User: {user_input} | Tâm trí: {internal_thought}"
            else:
                interaction_overlay = f"[Liên kết mới]: User: {user_input} -> Tôi nghĩ: {internal_thought}"

            # New markers are dedicated overlay records. This makes cleanup an
            # exact list operation and preserves literal marker-like user text.
            additions = [interaction_overlay]
            if reappraisal_marker is not None:
                additions.append(reappraisal_marker)
            retained_count = max(0, 10 - len(additions))
            retained = m.overlays[-retained_count:] if retained_count else []
            m.overlays = retained + additions
                
            m.strength = min(1.0, m.strength + 0.3)  # B7: recovery curve, không reset về 1.0
            m.emotional_layers = m.emotional_layers + 1
            if is_flashbulb: m.is_flashbulb = True
            m.valence, m.arousal, m.importance = (m.valence + new_valence) / 2, max(m.arousal, new_arousal), min(1.0, m.importance + 0.1)
            try:
                self.engine.memory.update_memory(m)
            except Exception:
                _restore_trace_state(m, previous_state)
                raise
            print(f"{Fore.CYAN}🔄 [MEMORY CONSOLIDATION]: Ký ức được nối tiếp vào mẩu tin cũ ({similar[0][0]:.2f}) - Tầng cảm xúc: {m.emotional_layers}{Style.RESET_ALL}")
        else:
            new_mem = MemoryTrace(content=f"User: {user_input} | Tôi nghĩ: {internal_thought}", type=perception.get('type', 'episodic'), valence=new_valence, arousal=new_arousal, importance=new_importance, is_flashbulb=is_flashbulb, overlays=([reappraisal_marker] if reappraisal_marker is not None else []))
            self.engine.memory.add_memory(new_mem)
            print(f"{Fore.CYAN}💾 [MEMORY STORED]: Ký ức mới được khắc ghi.{Style.RESET_ALL}")
        self.engine.memory.enforce_garbage_collection()

    def sleep(self):
        """Run critical sleep maintenance, commit sleep, then enrich best-effort."""
        print(f"\n{Fore.MAGENTA}💤 Aura đang ngủ... (Decay & Consolidation & Drift & Semanticization){Style.RESET_ALL}")
        self.last_sleep_outcome = SleepOutcome(sleep_committed=False)

        # Plan recovery without exposing it in RAM. Both durable critical
        # phases must finish before the sleep clock or homeostasis is reset.
        with self.engine.ego.lock:
            precommit_state = {
                field: copy.deepcopy(getattr(self.engine.ego, field))
                for field in (
                    "stress",
                    "fatigue",
                    "energy",
                    "atp_level",
                    "last_slept_time",
                    "days_without_sleep",
                    "_sleep_warning_cooldown",
                )
            }
            old_stress = self.engine.ego.stress
            old_fatigue = self.engine.ego.fatigue
            stress_drop = max(0.0, old_stress - max(0.0, old_stress - 0.3))
            fatigue_drop = max(0.0, old_fatigue)

        for phase, operation in (
            ("dream_consolidation", self._dream_consolidation_phase),
            ("decay", lambda: self._decay_phase(stress_drop, fatigue_drop)),
        ):
            try:
                operation()
            except BaseException as exc:
                with self.engine.ego.lock:
                    for field, value in precommit_state.items():
                        setattr(self.engine.ego, field, value)
                if isinstance(exc, Exception):
                    raise SleepMaintenanceError(phase, exc) from exc
                raise

        # This is the saga commit point. SelfModel holds its lock across the
        # atomic file replacement. The compatibility path below supplies the
        # same rollback semantics to lightweight integrations and test fakes.
        sleep_completed_at = time.time()
        try:
            self._commit_sleep_homeostasis(sleep_completed_at)
        except Exception as exc:
            raise SleepMaintenanceError("sleep_state_commit", exc) from exc

        self.last_sleep_outcome = SleepOutcome(
            sleep_committed=True,
            committed_at=sleep_completed_at,
        )

        enrichment_failures = []
        enrichments = [
            ("guilt_reflection", self._guilt_reflection_phase),
            ("cognitive_reappraisal", self._cognitive_reappraisal_phase),
            ("identity_evolution", self._sleep_identity_enrichment),
            ("tool_workshop", self._tool_workshop_phase),
            ("calibration", self._calibration_phase),
            ("belief_evolution", self._belief_evolution_phase),
        ]
        if self.slm_trainer:
            enrichments.append(
                ("slm_distillation", self.slm_trainer.distill_memories_to_dataset)
            )
        enrichments.extend((
            ("chronic_mood", self._sleep_chronic_mood_enrichment),
            ("memory_gc", self.engine.memory.enforce_garbage_collection),
            ("social_recovery", self._sleep_social_recovery_enrichment),
            ("threshold_reroll", self.engine.ego.reroll_thresholds),
            ("integrity_check", self._sleep_integrity_enrichment),
        ))
        for phase, operation in enrichments:
            try:
                operation()
            except Exception as exc:
                failure = SleepEnrichmentFailure(
                    phase=phase,
                    cause_type=type(exc).__name__,
                )
                enrichment_failures.append(failure)
                self._log_sleep_enrichment_failure(failure)

        self.last_sleep_outcome = SleepOutcome(
            sleep_committed=True,
            committed_at=sleep_completed_at,
            degraded_phases=tuple(enrichment_failures),
        )
        self._record_sleep_outcome()
        try:
            print(
                f"   -> Stress giảm còn {self.engine.ego.stress:.2f}, "
                "Fatigue reset về 0."
            )
        except Exception:
            # Console output is observability, not part of the durable saga.
            pass

    def _commit_sleep_homeostasis(self, sleep_completed_at):
        commit = getattr(self.engine.ego, "commit_sleep_state", None)
        if not callable(commit):
            raise TypeError("ego must implement commit_sleep_state")
        commit(sleep_completed_at)

    def _sleep_identity_enrichment(self):
        bio_report = f"""
        Báo cáo tình trạng sinh học:
        - ATP: {self.engine.ego.atp_level:.2f}
        - Energy: {self.engine.ego.energy:.2f}
        - Stress Sensitivity: {self.engine.ego.bio_controller.sensitivities.get('stress', 1.0):.2f}
        - Fatigue Critical: {self.engine.ego.fatigue_critical:.2f}
        """
        self._identity_evolution_phase(bio_report)

    def _sleep_chronic_mood_enrichment(self):
        mems_after = self.engine.memory.get_all()
        chronic_mood = self.engine.ego.calculate_chronic_mood(mems_after)
        with self.engine.ego.lock:
            self.engine.ego.mood = self.engine.ego.mood * 0.5 + chronic_mood * 0.5
            final_mood = self.engine.ego.mood
        print(
            f"   -> Chronic Mood Baseline: {chronic_mood:+.2f} | "
            f"Final Mood: {final_mood:+.2f}"
        )

    def _sleep_social_recovery_enrichment(self):
        with self.engine.ego.lock:
            self.engine.ego.social_need = min(
                1.0,
                self.engine.ego.social_need + 0.4,
            )
            self.engine.ego.curiosity = min(
                1.0,
                self.engine.ego.curiosity + 0.4,
            )

    def _sleep_integrity_enrichment(self):
        self.engine.ego.check_integrity(self.engine.memory.get_all())

    def _record_sleep_outcome(self):
        """Best-effort journal marker; journal failure cannot undo sleep."""

        try:
            from core.event_journal import record_current_event
            record_current_event(
                "maintenance.sleep",
                {
                    "sleep_committed": True,
                    "degraded_phase_count": len(
                        self.last_sleep_outcome.degraded_phases
                    ),
                },
                outcome="succeeded",
            )
        except Exception:
            # Observability is strictly fail-open after the commit point. Do
            # not include the recorder exception or let logger failure escape.
            try:
                from core.logger import get_logger
                get_logger("memory.ops").warning(
                    "Unable to record committed sleep outcome"
                )
            except Exception:
                pass

    @staticmethod
    def _log_sleep_enrichment_failure(failure):
        """Log safe metadata without letting observability fail the saga."""

        try:
            from core.logger import get_logger
            get_logger("memory.ops").error(
                "Sleep enrichment failed phase=%s cause_type=%s "
                "sleep_committed=True",
                failure.phase,
                failure.cause_type,
            )
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # Sleep sub-phases (tách ra để dễ test và debug)                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _log_dream_failure(message, *args):
        """Best-effort diagnostics that never change consolidation semantics."""

        try:
            from core.logger import get_logger
            get_logger("memory.ops").error(message, *args)
        except Exception:
            pass

    def _dream_ledger(self):
        ledger = getattr(self.engine, "operation_ledger", None)
        required = (
            "compare_and_swap",
            "create_or_get_plan",
            "get",
            "list_recoverable",
            "quarantine",
        )
        if ledger is None or any(
            not callable(getattr(ledger, method_name, None))
            for method_name in required
        ):
            return None
        return ledger

    def _quarantine_dream_operation(self, record, reason):
        ledger = self._dream_ledger()
        if ledger is None:
            return False
        return ledger.quarantine(
            record.op_id,
            reason=reason,
            expected_revision=record.revision,
            expected_status=record.status,
        )

    def _apply_dream_operation(self, initial_record):
        """Replay one immutable plan; external failures remain recoverable."""

        ledger = self._dream_ledger()
        if ledger is None:
            return False
        record = initial_record
        try:
            (
                parent_ids,
                fingerprints,
                source_policy,
                consolidation_id,
                consolidated_at,
                children,
            ) = _decode_dream_plan(record)
        except _DreamPlanError:
            self._quarantine_dream_operation(
                record,
                QuarantineReason.CORRUPTION,
            )
            return False

        if record.status is OperationStatus.COMMITTED:
            return True
        if record.status is OperationStatus.QUARANTINED:
            return False
        if record.status is OperationStatus.PLANNED:
            advanced = ledger.compare_and_swap(
                record.op_id,
                expected_revision=record.revision,
                expected_status=OperationStatus.PLANNED,
                new_status=OperationStatus.APPLYING,
            )
            record = ledger.get(record.op_id)
            if record is None:
                raise OperationCorruptionError(
                    "dream operation disappeared after CAS"
                )
            if not advanced and record.status is not OperationStatus.APPLYING:
                return record.status is OperationStatus.COMMITTED
        if record.status is not OperationStatus.APPLYING:
            return record.status is OperationStatus.COMMITTED

        mems = self.engine.memory.get_all()
        memories_by_id = {}
        for trace in mems:
            record_id = str(getattr(trace, "id", ""))
            if not record_id or record_id in memories_by_id:
                self._quarantine_dream_operation(
                    record,
                    QuarantineReason.PRECONDITION_MISMATCH,
                )
                return False
            memories_by_id[record_id] = trace

        parents = [memories_by_id.get(parent_id) for parent_id in parent_ids]
        if any(parent is None for parent in parents):
            self._quarantine_dream_operation(
                record,
                QuarantineReason.PRECONDITION_MISMATCH,
            )
            return False
        exact_parents = [parent for parent in parents if parent is not None]
        canonical_parent_ids = [
            str(parent.id)
            for parent in sorted(exact_parents, key=_memory_temporal_order)
        ]
        parent_states_are_valid = all(
            (
                not bool(getattr(parent, "is_consolidated_source", False))
                and str(getattr(parent, "consolidation_id", "") or "") == ""
                and getattr(parent, "consolidated_at", None) is None
            )
            or (
                bool(getattr(parent, "is_consolidated_source", False))
                and str(getattr(parent, "consolidation_id", "") or "")
                == consolidation_id
                and isinstance(
                    getattr(parent, "consolidated_at", None),
                    (int, float),
                )
                and not isinstance(
                    getattr(parent, "consolidated_at", None),
                    bool,
                )
                and math.isfinite(float(parent.consolidated_at))
                and float(parent.consolidated_at) == consolidated_at
            )
            for parent in exact_parents
        )
        try:
            fingerprints_match = all(
                fingerprint["sha256"] == _dream_parent_fingerprint(parent)
                for parent, fingerprint in zip(exact_parents, fingerprints)
            )
        except _DreamPlanError:
            fingerprints_match = False
        if (
            canonical_parent_ids != parent_ids
            or _homogeneous_policy(exact_parents) != source_policy
            or any(not _is_episodic_source(parent) for parent in exact_parents)
            or any(
                bool(getattr(parent, "consolidation_parent_ids", []) or [])
                for parent in exact_parents
            )
            or not parent_states_are_valid
            or not fingerprints_match
        ):
            self._quarantine_dream_operation(
                record,
                QuarantineReason.PRECONDITION_MISMATCH,
            )
            return False

        expected_by_id = {str(child.id): child for child in children}
        if len(expected_by_id) != len(children):
            self._quarantine_dream_operation(
                record,
                QuarantineReason.CORRUPTION,
            )
            return False
        manifest_records = [
            trace
            for trace in mems
            if str(getattr(trace, "consolidation_id", "") or "")
            == consolidation_id
            and bool(getattr(trace, "consolidation_parent_ids", []) or [])
        ]
        if any(
            str(trace.id) not in expected_by_id
            or not _dream_trace_exact_match(
                trace,
                expected_by_id.get(str(trace.id)),
            )
            for trace in manifest_records
        ):
            self._quarantine_dream_operation(
                record,
                QuarantineReason.PRECONDITION_MISMATCH,
            )
            return False

        missing_children = [
            child
            for child in children
            if str(child.id) not in memories_by_id
        ]
        if any(
            not _dream_trace_exact_match(
                memories_by_id.get(record_id),
                expected,
            )
            for record_id, expected in expected_by_id.items()
            if record_id in memories_by_id
        ):
            self._quarantine_dream_operation(
                record,
                QuarantineReason.PRECONDITION_MISMATCH,
            )
            return False

        with memory_context_scope(_write_context_for_scope(
            source_policy[0],
            origin_kind="consolidation",
            origin_source="sleep",
            carry_source_event=False,
        )):
            if missing_children:
                self.engine.memory.add_memories(missing_children)

            persisted = self.engine.memory.get_all()
            persisted_by_id = {}
            for trace in persisted:
                record_id = str(getattr(trace, "id", ""))
                if not record_id or record_id in persisted_by_id:
                    self._quarantine_dream_operation(
                        record,
                        QuarantineReason.PRECONDITION_MISMATCH,
                    )
                    return False
                persisted_by_id[record_id] = trace
            missing_persisted_children = [
                record_id
                for record_id in expected_by_id
                if record_id not in persisted_by_id
            ]
            if missing_persisted_children:
                # A batch API can acknowledge before every record is visible,
                # or a remote implementation can fail partially without
                # returning an exception.  The immutable plan makes retrying
                # only the missing children safe; do not terminally quarantine
                # an operation merely because a planned record is absent.
                raise MemoryStoreError(
                    "dream_children.readback",
                    record_count=len(missing_persisted_children),
                    cause_type="IncompleteReadback",
                )
            if any(
                not _dream_trace_exact_match(
                    persisted_by_id[record_id],
                    expected,
                )
                for record_id, expected in expected_by_id.items()
            ):
                self._quarantine_dream_operation(
                    record,
                    QuarantineReason.PRECONDITION_MISMATCH,
                )
                return False

            current_parents = [
                persisted_by_id.get(parent_id)
                for parent_id in parent_ids
            ]
            if any(parent is None for parent in current_parents):
                # They were present and validated immediately before the child
                # batch. Treat one missing readback as transient; a subsequent
                # replay will quarantine if the parent is genuinely gone.
                raise MemoryStoreError(
                    "dream_parents.readback",
                    record_count=sum(
                        parent is None for parent in current_parents
                    ),
                    cause_type="IncompleteReadback",
                )
            exact_current_parents = [
                parent for parent in current_parents if parent is not None
            ]
            try:
                current_fingerprints_match = all(
                    fingerprint["sha256"] == _dream_parent_fingerprint(parent)
                    for parent, fingerprint in zip(
                        exact_current_parents,
                        fingerprints,
                    )
                )
            except _DreamPlanError:
                current_fingerprints_match = False
            current_parent_states_are_valid = all(
                (
                    not bool(getattr(parent, "is_consolidated_source", False))
                    and str(getattr(parent, "consolidation_id", "") or "") == ""
                    and getattr(parent, "consolidated_at", None) is None
                )
                or (
                    bool(getattr(parent, "is_consolidated_source", False))
                    and str(getattr(parent, "consolidation_id", "") or "")
                    == consolidation_id
                    and isinstance(
                        getattr(parent, "consolidated_at", None),
                        (int, float),
                    )
                    and not isinstance(
                        getattr(parent, "consolidated_at", None),
                        bool,
                    )
                    and math.isfinite(float(parent.consolidated_at))
                    and float(parent.consolidated_at) == consolidated_at
                )
                for parent in exact_current_parents
            )
            if not current_fingerprints_match or not current_parent_states_are_valid:
                self._quarantine_dream_operation(
                    record,
                    QuarantineReason.PRECONDITION_MISMATCH,
                )
                return False

            all_marked = all(
                bool(getattr(parent, "is_consolidated_source", False))
                and str(getattr(parent, "consolidation_id", "") or "")
                == consolidation_id
                for parent in exact_current_parents
            )
            if not all_marked:
                previous_markers = [
                    (
                        parent,
                        parent.consolidation_id,
                        parent.consolidated_at,
                        parent.is_consolidated_source,
                    )
                    for parent in exact_current_parents
                ]
                for parent in exact_current_parents:
                    parent.consolidation_id = consolidation_id
                    parent.consolidated_at = consolidated_at
                    parent.is_consolidated_source = True
                try:
                    self.engine.memory.update_memories(exact_current_parents)
                except BaseException:
                    for parent, old_id, old_at, old_is_source in previous_markers:
                        parent.consolidation_id = old_id
                        parent.consolidated_at = old_at
                        parent.is_consolidated_source = old_is_source
                    raise

            marker_snapshot = {}
            for trace in self.engine.memory.get_all():
                record_id = str(getattr(trace, "id", ""))
                if not record_id or record_id in marker_snapshot:
                    self._quarantine_dream_operation(
                        record,
                        QuarantineReason.PRECONDITION_MISMATCH,
                    )
                    return False
                marker_snapshot[record_id] = trace

            missing_marker_parents = [
                parent_id
                for parent_id in parent_ids
                if parent_id not in marker_snapshot
            ]
            if missing_marker_parents:
                raise MemoryStoreError(
                    "dream_markers.readback",
                    record_count=len(missing_marker_parents),
                    cause_type="IncompleteReadback",
                )

            marker_parents = [marker_snapshot[parent_id] for parent_id in parent_ids]
            try:
                marker_fingerprints_match = all(
                    fingerprint["sha256"] == _dream_parent_fingerprint(parent)
                    for parent, fingerprint in zip(marker_parents, fingerprints)
                )
            except _DreamPlanError:
                marker_fingerprints_match = False
            if not marker_fingerprints_match:
                self._quarantine_dream_operation(
                    record,
                    QuarantineReason.PRECONDITION_MISMATCH,
                )
                return False

            incomplete_marker_count = 0
            for parent in marker_parents:
                exact_marker = (
                    bool(getattr(parent, "is_consolidated_source", False))
                    and str(getattr(parent, "consolidation_id", "") or "")
                    == consolidation_id
                    and isinstance(
                        getattr(parent, "consolidated_at", None),
                        (int, float),
                    )
                    and not isinstance(
                        getattr(parent, "consolidated_at", None),
                        bool,
                    )
                    and math.isfinite(float(parent.consolidated_at))
                    and float(parent.consolidated_at) == consolidated_at
                )
                clean_pre_state = (
                    not bool(getattr(parent, "is_consolidated_source", False))
                    and str(getattr(parent, "consolidation_id", "") or "") == ""
                    and getattr(parent, "consolidated_at", None) is None
                )
                if clean_pre_state:
                    incomplete_marker_count += 1
                elif not exact_marker:
                    self._quarantine_dream_operation(
                        record,
                        QuarantineReason.PRECONDITION_MISMATCH,
                    )
                    return False
            if incomplete_marker_count:
                raise MemoryStoreError(
                    "dream_markers.readback",
                    record_count=incomplete_marker_count,
                    cause_type="IncompleteReadback",
                )

        committed = ledger.compare_and_swap(
            record.op_id,
            expected_revision=record.revision,
            expected_status=OperationStatus.APPLYING,
            new_status=OperationStatus.COMMITTED,
        )
        if committed:
            return True
        current = ledger.get(record.op_id)
        return current is not None and current.status is OperationStatus.COMMITTED

    def _recover_dream_operation(self):
        ledger = self._dream_ledger()
        if ledger is None:
            return False
        saw_recoverable = False
        for record in ledger.list_recoverable(
            op_type=_DREAM_OPERATION_TYPE,
        ):
            saw_recoverable = True
            try:
                if self._apply_dream_operation(record):
                    return True
            except MemoryStoreError as exc:
                self._log_dream_failure(
                    "Semantic consolidation persistence failed "
                    "operation=%s cause_type=%s",
                    exc.operation,
                    exc.cause_type,
                )
                raise
            # A corrupt/precondition-bad operation was quarantined. Continue
            # so it cannot starve a healthy pending operation in this scan.
        return saw_recoverable

    def _finish_complete_legacy_dream_manifest(self, mems):
        """Finish only complete M2.1 manifests; incomplete ones fail closed."""

        memories_by_id = {str(memory.id): memory for memory in mems}
        if len(memories_by_id) != len(mems):
            return True
        manifest_groups = {}
        for trace in mems:
            consolidation_id = str(
                getattr(trace, "consolidation_id", "") or ""
            )
            parent_ids = tuple(
                getattr(trace, "consolidation_parent_ids", []) or []
            )
            expected_count = getattr(
                trace,
                "consolidation_expected_derived_count",
                0,
            )
            if (
                not consolidation_id
                or consolidation_id.startswith("belief-")
                or len(parent_ids) < 3
                or isinstance(expected_count, bool)
                or not isinstance(expected_count, int)
                or expected_count <= 0
            ):
                continue
            if (
                len(set(parent_ids)) != len(parent_ids)
                or any(
                    type(parent_id) is not str or not parent_id
                    for parent_id in parent_ids
                )
            ):
                return True
            key = (consolidation_id, parent_ids, expected_count)
            manifest_groups.setdefault(key, {})[str(trace.id)] = trace

        descriptors = {}
        for consolidation_id, parent_ids, expected_count in manifest_groups:
            descriptor = (parent_ids, expected_count)
            previous = descriptors.setdefault(consolidation_id, descriptor)
            if previous != descriptor:
                return True

        for manifest, derived_by_id in sorted(
            manifest_groups.items(),
            key=lambda item: (item[0][0], item[0][1]),
        ):
            consolidation_id, parent_ids, expected_count = manifest
            parents = [memories_by_id.get(parent_id) for parent_id in parent_ids]
            if any(parent is None for parent in parents):
                return True
            exact_parents = [parent for parent in parents if parent is not None]
            canonical_parent_ids = [
                str(parent.id)
                for parent in sorted(exact_parents, key=_memory_temporal_order)
            ]
            parent_policy = _homogeneous_policy(exact_parents)
            derived = list(derived_by_id.values())
            parents_already_marked = all(
                bool(getattr(parent, "is_consolidated_source", False))
                and str(getattr(parent, "consolidation_id", "") or "")
                == consolidation_id
                for parent in exact_parents
            )
            if parents_already_marked:
                if (
                    canonical_parent_ids != list(parent_ids)
                    or parent_policy is None
                    or len(derived) != expected_count
                    or not _valid_consolidation_child_set(
                        derived,
                        consolidation_id,
                        expected_count,
                    )
                    or any(
                        _memory_policy(trace) != parent_policy
                        or list(
                            getattr(trace, "provenance_parent_ids", []) or []
                        ) != list(parent_ids)
                        or getattr(trace, "origin_kind", "")
                        != "consolidation"
                        or getattr(trace, "origin_source", "") != "sleep"
                        for trace in derived
                    )
                ):
                    return True
                continue

            legacy_id = str(uuid.uuid5(
                uuid.NAMESPACE_URL,
                "aura:memory-consolidation:" + "|".join(parent_ids),
            ))
            if (
                consolidation_id != legacy_id
                or canonical_parent_ids != list(parent_ids)
                or parent_policy is None
                or any(not _is_episodic_source(parent) for parent in exact_parents)
                or any(
                    bool(getattr(parent, "consolidation_parent_ids", []) or [])
                    or str(getattr(parent, "consolidation_id", "") or "")
                    not in {"", consolidation_id}
                    for parent in exact_parents
                )
                or not _valid_consolidation_child_set(
                    derived,
                    consolidation_id,
                    expected_count,
                )
                or len(derived) != expected_count
            ):
                # An incomplete legacy manifest has no exact content plan and
                # must never ask the LLM to fill its gaps.
                return True

            legacy_traces = [
                trace
                for trace in derived
                if not (
                    _memory_policy(trace) == parent_policy
                    and list(getattr(trace, "provenance_parent_ids", []) or [])
                    == list(parent_ids)
                    and getattr(trace, "origin_kind", "") == "consolidation"
                    and getattr(trace, "origin_source", "") == "sleep"
                )
            ]
            if any(
                bool(getattr(trace, "provenance_parent_ids", []) or [])
                or getattr(trace, "origin_kind", "") not in {"unknown", "legacy"}
                or _memory_policy(trace) != parent_policy
                or not _valid_consolidation_child_id(
                    trace,
                    consolidation_id,
                    expected_count,
                )
                or getattr(trace, "source_event_id", None) is not None
                for trace in legacy_traces
            ):
                return True
            if legacy_traces:
                upgrade = getattr(
                    self.engine.memory,
                    "upgrade_legacy_provenance",
                    None,
                )
                if not callable(upgrade):
                    return True
                previous_lineage = [
                    (
                        trace,
                        trace.origin_kind,
                        trace.origin_source,
                        trace.source_event_id,
                        list(trace.provenance_parent_ids),
                    )
                    for trace in legacy_traces
                ]
                try:
                    with memory_context_scope(_write_context_for_scope(
                        parent_policy[0],
                        origin_kind="consolidation",
                        origin_source="sleep",
                        carry_source_event=False,
                    )):
                        for trace in legacy_traces:
                            upgraded = upgrade(trace)
                            trace.origin_kind = upgraded.origin_kind
                            trace.origin_source = upgraded.origin_source
                            trace.source_event_id = upgraded.source_event_id
                            trace.provenance_parent_ids = list(
                                upgraded.provenance_parent_ids
                            )
                except BaseException:
                    for (
                        trace,
                        old_kind,
                        old_source,
                        old_event_id,
                        old_parents,
                    ) in previous_lineage:
                        trace.origin_kind = old_kind
                        trace.origin_source = old_source
                        trace.source_event_id = old_event_id
                        trace.provenance_parent_ids = old_parents
                    raise

            if any(
                _memory_policy(trace) != parent_policy
                or trace.provenance_parent_ids != list(parent_ids)
                or trace.origin_kind != "consolidation"
                or trace.origin_source != "sleep"
                for trace in derived
            ):
                return True
            previous_markers = [
                (
                    parent,
                    parent.consolidation_id,
                    parent.consolidated_at,
                    parent.is_consolidated_source,
                )
                for parent in exact_parents
            ]
            consolidated_at = time.time()
            try:
                for parent in exact_parents:
                    parent.consolidation_id = consolidation_id
                    parent.consolidated_at = consolidated_at
                    parent.is_consolidated_source = True
                with memory_context_scope(_write_context_for_scope(
                    parent_policy[0],
                    origin_kind="consolidation",
                    origin_source="sleep",
                    carry_source_event=False,
                )):
                    self.engine.memory.update_memories(exact_parents)
            except BaseException:
                for parent, old_id, old_at, old_is_source in previous_markers:
                    parent.consolidation_id = old_id
                    parent.consolidated_at = old_at
                    parent.is_consolidated_source = old_is_source
                raise
            return True
        return False

    def _dream_consolidation_phase(self):
        """Consolidate via an immutable ledger plan before any memory write."""

        if self._recover_dream_operation():
            return

        mems = self.engine.memory.get_all()
        if self._finish_complete_legacy_dream_manifest(mems):
            return

        ledger = self._dream_ledger()
        if ledger is None:
            # Without a durable plan, a crash can hybridize outputs from two
            # independent LLM calls. Failing closed is the only safe fallback.
            return

        weak_episodic = [
            memory
            for memory in mems
            if _is_episodic_source(memory)
            and isinstance(getattr(memory, "strength", None), (int, float))
            and not isinstance(getattr(memory, "strength", None), bool)
            and math.isfinite(float(memory.strength))
            and memory.strength < 0.4
            and not bool(getattr(memory, "is_consolidated_source", False))
            and not str(getattr(memory, "consolidation_id", "") or "")
            and not bool(getattr(memory, "consolidation_parent_ids", []) or [])
            and _memory_policy(memory) is not None
        ]
        if len(weak_episodic) < 3:
            return

        policy_groups = {}
        for memory in sorted(weak_episodic, key=_memory_temporal_order):
            policy = _memory_policy(memory)
            if policy is not None:
                policy_groups.setdefault(policy, []).append(memory)
        eligible_groups = [
            (policy, group)
            for policy, group in policy_groups.items()
            if len(group) >= 3
        ]
        if not eligible_groups:
            return
        source_policy, selected_group = min(
            eligible_groups,
            key=lambda item: (_memory_temporal_order(item[1][0]), item[0]),
        )
        dream_mems = selected_group[:15]
        parent_ids = [str(memory.id) for memory in dream_mems]
        try:
            # Validate and bound sources before they enter either a prompt or
            # an immutable ledger record.
            for memory in dream_mems:
                _dream_parent_fingerprint(memory)
        except _DreamPlanError:
            return
        prompt_input = "\n".join(
            f"[{memory.created_at}] - {memory.content}"
            for memory in dream_mems
        )
        if len(prompt_input) > _MAX_DREAM_PROMPT_CHARS:
            return

        consolidation_id = _dream_consolidation_id(parent_ids)
        operation_id = _dream_operation_id(consolidation_id)
        existing = ledger.get(operation_id)
        if existing is not None:
            if existing.status in {
                OperationStatus.PLANNED,
                OperationStatus.APPLYING,
            }:
                self._apply_dream_operation(existing)
            return

        prompt = get_sleep_dream_prompt(prompt_input)
        raw_response, _ = self.engine.llm.generate_text(
            prompt,
            temperature=0.7,
            model_override=Config.DEEP_MODEL_NAME,
            bio_throttle=False,
        )
        try:
            insights = _parse_dream_insights(raw_response)
            plan = _build_dream_plan(
                dream_mems,
                insights,
                consolidation_id,
                source_policy,
            )
        except _DreamPlanError:
            try:
                from core.logger import get_logger
                get_logger("memory.ops").warning(
                    "Semantic consolidation rejected invalid inference batch"
                )
            except Exception:
                pass
            return

        # SQLite commit happens before the first Chroma mutation.
        record = ledger.create_or_get_plan(
            operation_id,
            _DREAM_OPERATION_TYPE,
            plan,
        )
        try:
            self._apply_dream_operation(record)
        except MemoryStoreError as exc:
            self._log_dream_failure(
                "Semantic consolidation persistence failed "
                "operation=%s cause_type=%s",
                exc.operation,
                exc.cause_type,
            )
            raise

    def _decay_phase(self, nightly_stress_drop=0.0, nightly_fatigue_drop=0.0):
        """Apply only wall-clock time not yet accounted for by each memory."""
        mems = self.engine.memory.get_all()
        ids_to_prune = []
        current_time = time.time()
        max_elapsed_days = 0.0
        protected_parent_ids = {
            parent_id
            for trace in mems
            for parent_id in (
                getattr(trace, "consolidation_parent_ids", []) or []
            )
            if isinstance(parent_id, str) and parent_id
        }

        for m in mems:
            checkpoint_pending = bool(
                getattr(m, "_last_decay_checkpoint_pending", False)
            )
            checkpoint = getattr(m, "last_decayed_at", None)
            if (
                checkpoint is None
                or isinstance(checkpoint, bool)
                or not isinstance(checkpoint, (int, float))
                or not math.isfinite(float(checkpoint))
            ):
                checkpoint = getattr(m, "created_at", current_time)
            if (
                isinstance(checkpoint, bool)
                or not isinstance(checkpoint, (int, float))
                or not math.isfinite(float(checkpoint))
            ):
                checkpoint = current_time

            elapsed_seconds = current_time - float(checkpoint)
            if elapsed_seconds < 1.0:
                # Let sub-second intervals accumulate instead of repeatedly
                # running trauma healing and stochastic semantic drift. A
                # legacy migration checkpoint is committed immediately.
                if checkpoint_pending:
                    self.engine.memory.update_memory(m)
                    try:
                        delattr(m, "_last_decay_checkpoint_pending")
                    except AttributeError:
                        pass
                continue
            elapsed_days = elapsed_seconds / 86400.0
            max_elapsed_days = max(max_elapsed_days, elapsed_days)
            previous_state = copy.deepcopy(m.__dict__)
            resilience_missing = object()
            previous_resilience = getattr(
                self.engine.ego,
                "resilience",
                resilience_missing,
            )
            try:
                m.decay(
                    stress_level=self.engine.ego.stress,
                    elapsed_days=elapsed_days,
                    homeostasis_recovery=True,
                    nightly_stress_drop=nightly_stress_drop,
                    nightly_fatigue_drop=nightly_fatigue_drop
                )
                m.last_decayed_at = current_time
                healing_baseline = {
                    field_name: getattr(m, field_name)
                    for field_name in ("valence", "impact_weight", "strength")
                }
                self.engine.process_trauma_healing(m) if hasattr(self.engine, 'process_trauma_healing') else self.engine.ego.process_trauma_healing(m)
                healing_scale = min(1.0, elapsed_days)
                for field_name, before_healing in healing_baseline.items():
                    after_healing = getattr(m, field_name)
                    if (
                        isinstance(before_healing, (int, float))
                        and not isinstance(before_healing, bool)
                        and isinstance(after_healing, (int, float))
                        and not isinstance(after_healing, bool)
                    ):
                        setattr(
                            m,
                            field_name,
                            before_healing
                            + (after_healing - before_healing) * healing_scale,
                        )
                if previous_resilience is not resilience_missing:
                    after_resilience = getattr(
                        self.engine.ego,
                        "resilience",
                        previous_resilience,
                    )
                    if isinstance(after_resilience, (int, float)):
                        self.engine.ego.resilience = (
                            previous_resilience
                            + (after_resilience - previous_resilience)
                            * healing_scale
                        )

                content_was_upserted = self.apply_semantic_drift(
                    m,
                    elapsed_days=elapsed_days,
                )
                if not content_was_upserted:
                    self.engine.memory.update_memory(m)
            except Exception:
                m.__dict__.clear()
                m.__dict__.update(previous_state)
                if previous_resilience is resilience_missing:
                    try:
                        delattr(self.engine.ego, "resilience")
                    except AttributeError:
                        pass
                else:
                    self.engine.ego.resilience = previous_resilience
                raise
            try:
                delattr(m, "_last_decay_checkpoint_pending")
            except AttributeError:
                pass

            if (
                getattr(m, "is_consolidated_source", False)
                or str(m.id) in protected_parent_ids
            ):
                continue
            if m.strength < 0.1 and not m.is_flashbulb and m.type != MemoryType.CORE:
                ids_to_prune.append(m.id)
            elif m.type == MemoryType.EPISODIC and m.importance < 0.2 and m.recall_count < 2:
                age_days = (current_time - m.created_at) / 86400
                if age_days > 7:
                    ids_to_prune.append(m.id)

        skills = getattr(self.engine, "skills", None)
        if skills is not None:
            decay_by_clock = getattr(skills, "decay_skills_by_clock", None)
            if callable(decay_by_clock):
                # Procedural memory owns a durable checkpoint independent of
                # whether episodic memory is empty or already committed.
                decay_by_clock(now=current_time)
            elif max_elapsed_days > 0.0:
                # Compatibility for light-weight fakes and older registries.
                skills.decay_skills(days_passed=max_elapsed_days)

        if ids_to_prune:
            print(f"{Fore.YELLOW}   🗑️ [SYNAPTIC PRUNING]: Xóa vĩnh viễn {len(ids_to_prune)} mảnh ký ức rác/cũ để giải phóng bộ não.{Style.RESET_ALL}")
            self.engine.memory.remove_many(ids_to_prune)

    def _guilt_reflection_phase(self):
        """Phase 3: Nếu tâm lý bất ổn, Aura tự xét lại hành vi trong ngày."""
        negative_stats_count = sum(1 for val in [
            self.engine.ego.stress, self.engine.ego.fatigue,
            float(self.engine.ego.mood < -0.5), float(self.engine.ego.is_identity_crisis)
        ] if val > 0.5)

        if self.engine.ego.stress > 0.75 or negative_stats_count >= 2:
            with self.engine.stm_lock:
                buffer_snapshot = list(self.engine.short_term_buffer)
            if len(buffer_snapshot) > 0:
                print(f"{Fore.LIGHTBLACK_EX}🔍 [GUILT REFLECTION]: Đang suy ngẫm lại hành vi trong ngày...{Style.RESET_ALL}")
                guilt_prompt = (
                    f"Đây là lịch sử trò chuyện gần đây:\n{buffer_snapshot}\n"
                    "Bạn có nói câu nào vô tâm, có thái độ gắt gỏng, lạnh nhạt không đáng có không? "
                    "Trả lời 'CÓ' hoặc 'KHÔNG'. Nếu CÓ, hãy nêu lý do thành 1 câu ngắn bắt đầu bằng 'Lý do: '."
                )
                guilt_res, _ = self.engine.llm.generate_text(guilt_prompt, temperature=0.2, bio_throttle=False); guilt_res = guilt_res.strip()
                # B15: dùng startswith — tránh 'CÓ thể' bị detect lầm
                if guilt_res.strip().upper().startswith("CÓ") or "LÝ DO" in guilt_res.upper():
                    guilt_reason = guilt_res.replace("CÓ", "").strip(":- ,.\n")
                    if guilt_reason:
                        guilt_mem = MemoryTrace(
                            content=f"Tôi cảm thấy ân hận vì cách hành xử của mình lúc trước: {guilt_reason}. Lần sau phải chú ý ôn hòa hơn.",
                            type=MemoryType.EPISODIC,
                            valence=-0.6,
                            arousal=0.5,
                            importance=0.8,
                            scope=MemoryScope.OWNER.value,
                            privacy=MemoryPrivacy.STANDARD.value,
                            origin_kind="guilt_reflection",
                            origin_source="sleep",
                        )
                        with memory_context_scope(_write_context_for_scope(
                            MemoryScope.OWNER.value,
                            origin_kind="guilt_reflection",
                            origin_source="sleep",
                        )):
                            self.engine.memory.add_memory(guilt_mem)
                        print(f"{Fore.MAGENTA}😔 [GUILT]: Aura cảm thấy hối hận vì: {guilt_reason}{Style.RESET_ALL}")
    
    @staticmethod
    def _log_reappraisal_failure(level, message, *args):
        try:
            from core.logger import get_logger
            getattr(get_logger("memory.ops"), level)(message, *args)
        except BaseException:
            pass

    def _reappraisal_ledger(self):
        ledger = getattr(self.engine, "operation_ledger", None)
        required = (
            "compare_and_swap",
            "create_or_get_plan",
            "get",
            "list_recoverable",
            "quarantine",
        )
        if ledger is None or any(
            not callable(getattr(ledger, method_name, None))
            for method_name in required
        ):
            return None
        return ledger

    def _quarantine_reappraisal_operation(self, record, reason):
        ledger = self._reappraisal_ledger()
        if ledger is None:
            return False
        return ledger.quarantine(
            record.op_id,
            reason=reason,
            expected_revision=record.revision,
            expected_status=record.status,
        )

    @staticmethod
    def _reappraisal_child_exact(actual, expected):
        if actual is None or expected is None:
            return False
        try:
            return _canonical_json(
                _dream_trace_to_spec(actual)
            ) == _canonical_json(_dream_trace_to_spec(expected))
        except (AttributeError, TypeError, ValueError, OverflowError):
            return False

    def _finish_one_legacy_reappraisal_child(self, mems):
        """Complete a provable pre-ledger EVOLVE without another LLM call."""

        memories_by_id = {str(memory.id): memory for memory in mems}
        if len(memories_by_id) != len(mems):
            return True
        for parent in sorted(mems, key=_memory_temporal_order):
            parent_policy = _memory_policy(parent)
            if parent_policy is None or type(parent.overlays) is not list:
                continue
            legacy_present = (
                _REAPPRAISAL_LEGACY_MARKER in str(parent.content)
                or any(
                    _REAPPRAISAL_LEGACY_MARKER in str(overlay)
                    for overlay in parent.overlays
                )
            )
            if not legacy_present:
                continue
            child = memories_by_id.get(
                _legacy_reappraisal_child_id(str(parent.id))
            )
            if child is None:
                continue
            if (
                not _has_memory_type(child, MemoryType.CORE)
                or _memory_policy(child) != parent_policy
                or child.origin_kind != "reappraisal"
                or child.origin_source != "sleep"
                or list(child.provenance_parent_ids) != [str(parent.id)]
                or "Belief" not in str(child.content)
                or child.consolidation_id
                or child.consolidation_parent_ids
                or child.consolidation_expected_derived_count != 0
            ):
                continue

            previous_state = copy.deepcopy(parent.__dict__)
            cleaned_content, content_locator = (
                _remove_one_legacy_reappraisal_marker(parent.content)
            )
            cleaned_overlays = list(parent.overlays)
            overlay_changed = False
            if content_locator is None:
                for index, overlay in enumerate(cleaned_overlays):
                    cleaned, locator = _remove_one_legacy_reappraisal_marker(
                        overlay
                    )
                    if locator is not None:
                        cleaned_overlays[index] = cleaned
                        overlay_changed = True
                        break
            parent.content = cleaned_content
            parent.overlays = cleaned_overlays
            try:
                with memory_context_scope(_write_context_for_scope(
                    parent_policy[0],
                    origin_kind="reappraisal",
                    origin_source="sleep",
                    carry_source_event=False,
                )):
                    if content_locator is not None:
                        self.engine.memory.upsert_memory(parent)
                    elif overlay_changed:
                        self.engine.memory.update_memory(parent)
                    else:
                        _restore_trace_state(parent, previous_state)
                        continue
            except BaseException:
                _restore_trace_state(parent, previous_state)
                raise
            return True
        return False

    def _migrate_one_legacy_reappraisal_marker(self, mems):
        """Persist one deterministic attempt marker before any new analysis."""

        for parent in sorted(mems, key=_memory_temporal_order):
            parent_policy = _memory_policy(parent)
            if parent_policy is None or type(parent.overlays) is not list:
                continue
            cleaned_content, locator = _remove_one_legacy_reappraisal_marker(
                parent.content
            )
            field = "content"
            overlay_index = None
            cleaned_overlay = None
            if locator is None:
                for index, overlay in enumerate(parent.overlays):
                    candidate, candidate_locator = (
                        _remove_one_legacy_reappraisal_marker(overlay)
                    )
                    if candidate_locator is not None:
                        field = f"overlay:{index}"
                        overlay_index = index
                        cleaned_overlay = candidate
                        locator = candidate_locator
                        break
            if locator is None:
                continue
            attempt_id = str(uuid.uuid5(
                uuid.NAMESPACE_URL,
                "aura:reappraisal-legacy:"
                + _canonical_json({
                    "field": field,
                    "locator": locator,
                    "parent_id": str(parent.id),
                }),
            ))
            marker = _reappraisal_marker(attempt_id)
            previous_state = copy.deepcopy(parent.__dict__)
            content_changed = field == "content"
            if content_changed:
                parent.content = cleaned_content
            else:
                parent.overlays[overlay_index] = cleaned_overlay
            if marker not in parent.overlays:
                parent.overlays.append(marker)
            try:
                with memory_context_scope(_write_context_for_scope(
                    parent_policy[0],
                    origin_kind="reappraisal",
                    origin_source="sleep",
                    carry_source_event=False,
                )):
                    if content_changed:
                        self.engine.memory.upsert_memory(parent)
                    else:
                        self.engine.memory.update_memory(parent)
            except BaseException:
                _restore_trace_state(parent, previous_state)
                raise
            return True
        return False

    def _rekey_reappraisal_candidate(
        self,
        parent: MemoryTrace,
        old_attempt_id: str,
    ) -> bool:
        """Replace a conflicting attempt marker on a second parent with a deterministic new attempt marker."""

        parent_policy = _memory_policy(parent)
        if parent_policy is None or type(parent.overlays) is not list:
            return False
        try:
            parent_fingerprint = _reappraisal_parent_fingerprint(parent)
            old_marker = _reappraisal_marker(old_attempt_id)
            new_attempt_id = _reappraisal_rekeyed_attempt_id(
                old_attempt_id,
                str(parent.id),
            )
            new_marker = _reappraisal_marker(new_attempt_id)
        except _DreamPlanError:
            return False

        if (
            parent.overlays.count(old_marker) != 1
            or new_marker in parent.overlays
        ):
            return False

        replaced = False
        new_overlays = []
        for overlay in parent.overlays:
            if not replaced and overlay == old_marker:
                new_overlays.append(new_marker)
                replaced = True
            else:
                new_overlays.append(overlay)
        if not replaced:
            return False

        previous_state = copy.deepcopy(parent.__dict__)
        parent.overlays = new_overlays
        try:
            with memory_context_scope(_write_context_for_scope(
                parent_policy[0],
                origin_kind="reappraisal",
                origin_source="sleep",
                carry_source_event=False,
            )):
                self.engine.memory.update_memory(parent)

            parent_snapshot = {}
            for trace in self.engine.memory.get_all():
                record_id = str(getattr(trace, "id", ""))
                if not record_id or record_id in parent_snapshot:
                    raise MemoryStoreError(
                        "reappraisal_rekey.readback",
                        cause_type="IncompleteReadback",
                    )
                parent_snapshot[record_id] = trace

            persisted_parent = parent_snapshot.get(str(parent.id))
            if persisted_parent is None:
                raise MemoryStoreError(
                    "reappraisal_rekey.readback",
                    cause_type="IncompleteReadback",
                )

            try:
                persisted_matches = (
                    _memory_policy(persisted_parent) == parent_policy
                    and _reappraisal_parent_fingerprint(persisted_parent)
                    == parent_fingerprint
                )
            except _DreamPlanError:
                persisted_matches = False
            if not persisted_matches:
                raise MemoryStoreError(
                    "reappraisal_rekey.readback",
                    cause_type="IncompleteReadback",
                )

            persisted_overlays = getattr(persisted_parent, "overlays", None)
            if type(persisted_overlays) is not list:
                raise MemoryStoreError(
                    "reappraisal_rekey.readback",
                    cause_type="IncompleteReadback",
                )
            if old_marker in persisted_overlays:
                raise MemoryStoreError(
                    "reappraisal_rekey.readback",
                    cause_type="IncompleteReadback",
                )
            if persisted_overlays.count(new_marker) != 1:
                raise MemoryStoreError(
                    "reappraisal_rekey.readback",
                    cause_type="IncompleteReadback",
                )
        except BaseException:
            _restore_trace_state(parent, previous_state)
            raise
        return True

    def _apply_reappraisal_operation(self, initial_record):
        ledger = self._reappraisal_ledger()
        if ledger is None:
            return False
        record = initial_record
        try:
            (
                parent_id,
                _attempt_id,
                marker,
                policy,
                fingerprint,
                target_valence,
                expected_child,
            ) = _decode_reappraisal_plan(record)
        except _DreamPlanError:
            self._quarantine_reappraisal_operation(
                record,
                QuarantineReason.CORRUPTION,
            )
            return False
        if record.status is OperationStatus.COMMITTED:
            return True
        if record.status is OperationStatus.QUARANTINED:
            return False
        if record.status is OperationStatus.PLANNED:
            advanced = ledger.compare_and_swap(
                record.op_id,
                expected_revision=record.revision,
                expected_status=OperationStatus.PLANNED,
                new_status=OperationStatus.APPLYING,
            )
            record = ledger.get(record.op_id)
            if record is None:
                raise OperationCorruptionError(
                    "reappraisal operation disappeared after CAS"
                )
            if not advanced and record.status is not OperationStatus.APPLYING:
                return record.status is OperationStatus.COMMITTED
        if record.status is not OperationStatus.APPLYING:
            return record.status is OperationStatus.COMMITTED

        mems = self.engine.memory.get_all()
        memories_by_id = {}
        for trace in mems:
            record_id = str(getattr(trace, "id", ""))
            if not record_id or record_id in memories_by_id:
                self._quarantine_reappraisal_operation(
                    record,
                    QuarantineReason.PRECONDITION_MISMATCH,
                )
                return False
            memories_by_id[record_id] = trace
        parent = memories_by_id.get(parent_id)
        if parent is None:
            self._quarantine_reappraisal_operation(
                record,
                QuarantineReason.PRECONDITION_MISMATCH,
            )
            return False
        try:
            parent_matches = (
                _memory_policy(parent) == policy
                and _reappraisal_parent_fingerprint(parent) == fingerprint
            )
        except _DreamPlanError:
            parent_matches = False
        if not parent_matches:
            self._quarantine_reappraisal_operation(
                record,
                QuarantineReason.PRECONDITION_MISMATCH,
            )
            return False
        parent_overlays = getattr(parent, "overlays", None)
        if type(parent_overlays) is not list:
            self._quarantine_reappraisal_operation(
                record,
                QuarantineReason.PRECONDITION_MISMATCH,
            )
            return False
        marker_count = sum(overlay == marker for overlay in parent_overlays)
        if marker_count > 1:
            self._quarantine_reappraisal_operation(
                record,
                QuarantineReason.PRECONDITION_MISMATCH,
            )
            return False

        child_id = str(expected_child.id) if expected_child is not None else None
        actual_child = memories_by_id.get(child_id) if child_id is not None else None
        if actual_child is not None and not self._reappraisal_child_exact(
            actual_child,
            expected_child,
        ):
            self._quarantine_reappraisal_operation(
                record,
                QuarantineReason.PRECONDITION_MISMATCH,
            )
            return False

        post_valence_matches = (
            target_valence is None
            or (
                isinstance(parent.valence, (int, float))
                and not isinstance(parent.valence, bool)
                and math.isfinite(float(parent.valence))
                and float(parent.valence) == target_valence
            )
        )
        if marker_count == 0:
            if (
                not post_valence_matches
                or (expected_child is not None and actual_child is None)
            ):
                self._quarantine_reappraisal_operation(
                    record,
                    QuarantineReason.PRECONDITION_MISMATCH,
                )
                return False
        else:
            with memory_context_scope(_write_context_for_scope(
                policy[0],
                origin_kind="reappraisal",
                origin_source="sleep",
                carry_source_event=False,
            )):
                if expected_child is not None and actual_child is None:
                    self.engine.memory.add_memory(expected_child)
                    child_snapshot = {}
                    for trace in self.engine.memory.get_all():
                        record_id = str(getattr(trace, "id", ""))
                        if not record_id or record_id in child_snapshot:
                            self._quarantine_reappraisal_operation(
                                record,
                                QuarantineReason.PRECONDITION_MISMATCH,
                            )
                            return False
                        child_snapshot[record_id] = trace
                    actual_child = child_snapshot.get(child_id)
                    if actual_child is None:
                        raise MemoryStoreError(
                            "reappraisal_child.readback",
                            cause_type="IncompleteReadback",
                        )
                    if not self._reappraisal_child_exact(
                        actual_child,
                        expected_child,
                    ):
                        self._quarantine_reappraisal_operation(
                            record,
                            QuarantineReason.PRECONDITION_MISMATCH,
                        )
                        return False

                previous_state = copy.deepcopy(parent.__dict__)
                if target_valence is not None:
                    parent.valence = target_valence
                removed = False
                retained_overlays = []
                for overlay in parent.overlays:
                    if not removed and overlay == marker:
                        removed = True
                        continue
                    retained_overlays.append(overlay)
                if not removed:
                    self._quarantine_reappraisal_operation(
                        record,
                        QuarantineReason.PRECONDITION_MISMATCH,
                    )
                    return False
                parent.overlays = retained_overlays
                try:
                    self.engine.memory.update_memory(parent)
                except BaseException:
                    _restore_trace_state(parent, previous_state)
                    raise

                parent_snapshot = {}
                for trace in self.engine.memory.get_all():
                    record_id = str(getattr(trace, "id", ""))
                    if not record_id or record_id in parent_snapshot:
                        self._quarantine_reappraisal_operation(
                            record,
                            QuarantineReason.PRECONDITION_MISMATCH,
                        )
                        return False
                    parent_snapshot[record_id] = trace
                persisted_parent = parent_snapshot.get(parent_id)
                if persisted_parent is None:
                    raise MemoryStoreError(
                        "reappraisal_parent.readback",
                        cause_type="IncompleteReadback",
                    )
                try:
                    persisted_matches = (
                        _memory_policy(persisted_parent) == policy
                        and _reappraisal_parent_fingerprint(persisted_parent)
                        == fingerprint
                    )
                except _DreamPlanError:
                    persisted_matches = False
                if not persisted_matches:
                    self._quarantine_reappraisal_operation(
                        record,
                        QuarantineReason.PRECONDITION_MISMATCH,
                    )
                    return False
                persisted_overlays = getattr(persisted_parent, "overlays", None)
                if type(persisted_overlays) is not list:
                    self._quarantine_reappraisal_operation(
                        record,
                        QuarantineReason.PRECONDITION_MISMATCH,
                    )
                    return False
                if marker in persisted_overlays:
                    raise MemoryStoreError(
                        "reappraisal_parent.readback",
                        cause_type="IncompleteReadback",
                    )
                persisted_valence = getattr(persisted_parent, "valence", None)
                if target_valence is not None and (
                    isinstance(persisted_valence, bool)
                    or not isinstance(persisted_valence, (int, float))
                    or not math.isfinite(float(persisted_valence))
                    or float(persisted_valence) != target_valence
                ):
                    self._quarantine_reappraisal_operation(
                        record,
                        QuarantineReason.PRECONDITION_MISMATCH,
                    )
                    return False

        committed = ledger.compare_and_swap(
            record.op_id,
            expected_revision=record.revision,
            expected_status=OperationStatus.APPLYING,
            new_status=OperationStatus.COMMITTED,
        )
        if committed:
            return True
        current = ledger.get(record.op_id)
        return current is not None and current.status is OperationStatus.COMMITTED

    def _recover_reappraisal_operation(self):
        ledger = self._reappraisal_ledger()
        if ledger is None:
            return False
        saw_recoverable = False
        for record in ledger.list_recoverable(
            op_type=_REAPPRAISAL_OPERATION_TYPE,
        ):
            saw_recoverable = True
            try:
                if self._apply_reappraisal_operation(record):
                    return True
            except MemoryStoreError as exc:
                self._log_reappraisal_failure(
                    "error",
                    "Cognitive reappraisal persistence failed "
                    "operation=%s cause_type=%s",
                    exc.operation,
                    exc.cause_type,
                )
                raise
        return saw_recoverable

    def _cognitive_reappraisal_phase(self):
        """Apply one per-attempt immutable reappraisal plan."""

        ledger = self._reappraisal_ledger()
        if ledger is None:
            return
        if self._recover_reappraisal_operation():
            return
        mems = self.engine.memory.get_all()
        try:
            if self._finish_one_legacy_reappraisal_child(mems):
                return
            if self._migrate_one_legacy_reappraisal_marker(mems):
                mems = self.engine.memory.get_all()
        except MemoryStoreError as exc:
            self._log_reappraisal_failure(
                "error",
                "Cognitive reappraisal migration failed "
                "operation=%s cause_type=%s",
                exc.operation,
                exc.cause_type,
            )
            raise

        candidates = []
        for parent in sorted(mems, key=_memory_temporal_order):
            if (
                _memory_policy(parent) is None
                or type(parent.overlays) is not list
            ):
                continue
            for overlay in parent.overlays:
                attempt_id = _reappraisal_attempt_from_marker(overlay)
                if attempt_id is not None:
                    candidates.append((parent, attempt_id, overlay))
        if not candidates:
            return
        print(
            f"\n{Fore.LIGHTBLUE_EX}🧠 [COGNITIVE REAPPRAISAL]: "
            f"Aura đang chiêm nghiệm về {len(candidates)} mâu thuẫn nhận thức..."
            f"{Style.RESET_ALL}"
        )

        for parent, attempt_id, _marker in candidates:
            operation_id = _reappraisal_operation_id(attempt_id)
            existing = ledger.get(operation_id)
            if existing is not None:
                existing_parent_id = None
                try:
                    (
                        existing_parent_id,
                        _existing_attempt_id,
                        _existing_marker,
                        _existing_policy,
                        _existing_fingerprint,
                        _existing_target_valence,
                        _existing_child,
                    ) = _decode_reappraisal_plan(existing)
                except _DreamPlanError:
                    if isinstance(existing.plan, dict):
                        existing_parent_id = existing.plan.get("parent_id")

                if existing_parent_id != str(parent.id):
                    try:
                        if self._rekey_reappraisal_candidate(parent, attempt_id):
                            return
                    except MemoryStoreError as exc:
                        self._log_reappraisal_failure(
                            "error",
                            "Cognitive reappraisal re-key failed "
                            "operation=%s cause_type=%s",
                            exc.operation,
                            exc.cause_type,
                        )
                        raise
                    continue

                if existing.status in {
                    OperationStatus.PLANNED,
                    OperationStatus.APPLYING,
                }:
                    self._apply_reappraisal_operation(existing)
                    return
                continue
            try:
                _reappraisal_parent_fingerprint(parent)
                beliefs = self.engine.ego.get_active_beliefs(
                    context_query=parent.content
                )
                belief_str = (
                    "\n- ".join(beliefs)
                    if beliefs
                    else "Chưa có niềm tin cụ thể."
                )
                prompt = f"""
                Aura đang gặp mâu thuẫn giữa niềm tin cũ và thông tin mới nhận được.

                Niềm tin hiện tại:
                - {belief_str}

                Thông tin mới gây mâu thuẫn:
                '{parent.content}'

                Nhiệm vụ: Phân tích liệu Aura nên giữ vững niềm tin cũ hay 'tiến hóa' niềm tin để phù hợp với thực tế mới.

                TRẢ VỀ DUY NHẤT ĐỊNH DẠNG JSON:
                {{
                    "action": "EVOLVE" | "SOFTEN" | "REJECT",
                    "reasoning": "Lý do ngắn gọn",
                    "new_belief": "Niềm tin mới nếu EVOLVE, nếu không để trống"
                }}
                """
                raw_response, _ = self.engine.llm.generate_text(
                    prompt,
                    temperature=0.3,
                    bio_throttle=False,
                )
                decision = _parse_reappraisal_decision(raw_response)
                plan = _build_reappraisal_plan(
                    parent,
                    attempt_id,
                    decision,
                )
                record = ledger.create_or_get_plan(
                    operation_id,
                    _REAPPRAISAL_OPERATION_TYPE,
                    plan,
                )
            except _DreamPlanError:
                self._log_reappraisal_failure(
                    "warning",
                    "Cognitive reappraisal rejected invalid analysis",
                )
                return
            except Exception as exc:
                self._log_reappraisal_failure(
                    "warning",
                    "Cognitive reappraisal analysis failed cause_type=%s",
                    type(exc).__name__,
                )
                return
            self._apply_reappraisal_operation(record)
            return

    def _identity_evolution_phase(self, bio_report: str = None):
        """[Phase 21] Bộ máy Phản tư: Tổng hợp STM trong ngày và đúc kết thành Core Identity & Values."""
        from core import identity_drift

        last_reflection = float(
            getattr(self.engine.ego, "last_identity_reflection", 0.0) or 0.0
        )
        if time.time() - last_reflection < identity_drift.MIN_REFLECTION_GAP_SECONDS:
            return  # đã phản tư trong đêm nay; giấc ngủ trưa không đúc kết lại
        with self.engine.stm_lock:
            buffer_snapshot = list(self.engine.short_term_buffer)
        if not buffer_snapshot or len(buffer_snapshot) < 4:
            return  # Quá ít tương tác để đúc kết
        with self.engine.ego.lock:
            previous_identity = self.engine.ego.evolved_insight
            previous_lessons = list(self.engine.ego.actionable_lessons)
            previous_pending = getattr(self.engine.ego, "pending_identity_insight", "")
            
        print(f"\n{Fore.LIGHTBLUE_EX}🧠 [IDENTITY EVOLUTION]: Trích xuất bài học về bản thể và hệ giá trị...{Style.RESET_ALL}")
        history_str = "\n".join(buffer_snapshot)
        
        current_values = self.engine.value_system.get_moral_context()
        
        prompt = f"""
        Bạn là Aura. Hãy phản tư về những tương tác trong ngày hôm nay:
        --- BẢN SẮC HIỆN TẠI CỦA BẠN ---
        {previous_identity}
        --- LỊCH SỬ TRÒ CHUYỆN ---
        {history_str}
        
        --- HỆ GIÁ TRỊ HIỆN TẠI ---
        {current_values}
        
        Nhiệm vụ:
        1. Đúc kết một câu trần thuật về bản sắc (Tôi là ai trong mắt người dùng?). Đây là CHỈNH SỬA
           của "bản sắc hiện tại" ở trên: giữ phần cốt lõi, chỉ điều chỉnh theo những gì hôm nay
           thật sự làm bạn thay đổi. Một ngày bình thường không làm con người đổi hẳn tính cách.
        2. Rút ra tối đa 3 BÀI HỌC HÀNH ĐỘNG (Actionable Lessons) để cải thiện giao tiếp hoặc tính cách vào ngày mai (Ví dụ: "Tôi nên bớt luyên thuyên khi User đang bận", "Tôi cần thể hiện sự quan tâm nhiều hơn đến sức khỏe của User").
        3. Xác định xem hệ giá trị (Core Values) hoặc nhận thức về giá trị của User (User Values) có thay đổi không.
        
        TRẢ VỀ DUY NHẤT ĐỊNH DẠNG JSON:
        {{
            "insight": "Câu trần thuật ngôi thứ nhất",
            "actionable_lessons": ["bài học 1", "bài học 2"],
            "value_updates": [
                {{"name": "Tên giá trị", "sentiment": <float -1.0 đến 1.0>, "type": "core" | "user", "reason": "Tại sao?"}}
            ]
        }}
        """
        try:
            raw_res, _ = self.engine.llm.generate_text(prompt, temperature=0.7, bio_throttle=False)
            import json
            json_str = raw_res.strip().replace("```json", "").replace("```", "").strip()
            data = json.loads(json_str)

            if not isinstance(data, dict):
                raise ValueError("identity payload must be an object")
            insight = data.get("insight", "")
            lessons = data.get("actionable_lessons", [])
            updates = data.get("value_updates", [])
            if not isinstance(insight, str):
                raise ValueError("identity insight must be text")
            insight = insight.strip()
            if not isinstance(lessons, list) or any(
                not isinstance(lesson, str) for lesson in lessons
            ):
                raise ValueError("identity lessons must be text list")
            lessons = [lesson.strip() for lesson in lessons if lesson.strip()]
            if not isinstance(updates, list):
                raise ValueError("identity value updates must be a list")
            validated_updates = []
            for update in updates:
                if not isinstance(update, dict):
                    raise ValueError("identity value update must be an object")
                name = update.get("name")
                sentiment = update.get("sentiment")
                value_type = update.get("type", "core")
                reason = update.get("reason", "")
                if (
                    not isinstance(name, str)
                    or not name.strip()
                    or isinstance(sentiment, bool)
                    or not isinstance(sentiment, (int, float))
                    or not math.isfinite(float(sentiment))
                    or not -1.0 <= float(sentiment) <= 1.0
                    or value_type not in {"core", "user"}
                    or not isinstance(reason, str)
                ):
                    raise ValueError("invalid identity value update")
                validated_updates.append({
                    "name": name.strip(),
                    "sentiment": float(sentiment),
                    "type": value_type,
                    "reason": reason,
                })
            with self.engine.ego.lock:
                self.engine.ego.last_identity_reflection = time.time()
            adopt_insight = False
            if insight and len(insight) > 10:
                adopt_insight, pending_insight = identity_drift.decide(
                    previous_identity, insight, previous_pending
                )
                with self.engine.ego.lock:
                    self.engine.ego.pending_identity_insight = pending_insight
                if not adopt_insight:
                    print(
                        f"{Fore.LIGHTBLUE_EX}🌗 [IDENTITY]: Hôm nay khiến Aura nghĩ khác hẳn về bản thân; "
                        f"cần thêm thời gian trước khi tin vào điều đó.{Style.RESET_ALL}"
                    )
            if adopt_insight:
                identity_memory = MemoryTrace(
                    id=str(uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"aura:identity-insight:{insight}",
                    )),
                    content=f"Nhận thức Bản thể (Core Identity Updated): {insight}",
                    type=MemoryType.CORE,
                    valence=0.5,
                    arousal=0.3,
                    importance=1.0,
                    is_flashbulb=True,
                    scope=MemoryScope.OWNER.value,
                    privacy=MemoryPrivacy.STANDARD.value,
                    origin_kind="identity_evolution",
                    origin_source="sleep",
                )
                with memory_context_scope(_write_context_for_scope(
                    MemoryScope.OWNER.value,
                    origin_kind="identity_evolution",
                    origin_source="sleep",
                )):
                    self.engine.memory.add_memory(identity_memory)
                with self.engine.ego.lock:
                    self.engine.ego.evolved_insight = insight
                print(f"{Fore.GREEN}🌱 [CORE IDENTITY EVOLVED]: {insight}{Style.RESET_ALL}")
            
            if lessons:
                with self.engine.ego.lock:
                    self.engine.ego.actionable_lessons = lessons[:5] # Giới hạn 5 bài học gần nhất
                print(f"{Fore.CYAN}📚 [LESSONS LEARNED]: {len(lessons)} bài học mới đã được ghi vào bản ngã.{Style.RESET_ALL}")
            
            for up in validated_updates:
                v_name = up.get("name")
                v_sent = up.get("sentiment")
                v_type = up.get("type", "core")
                v_reason = up.get("reason", "")
                
                if v_name and v_sent is not None:
                    if v_type == "core":
                        self.engine.value_system.update_core_value(v_name, v_sent)
                    else:
                        self.engine.value_system.update_user_value(v_name, v_sent)
                    print(f"{Fore.MAGENTA}⚖️ [VALUE SHIFT]: {v_name} ({v_type}) -> {v_sent:.2f} (Lý do: {v_reason}){Style.RESET_ALL}")

            # [Phase 23] Sync to identity.json for permanent personality evolution
            try:
                # Keep keys this phase does not own (e.g. override_device_id).
                identity_data = {}
                try:
                    with open("identity.json", "r", encoding="utf-8") as f:
                        existing = json.load(f)
                    if isinstance(existing, dict):
                        identity_data.update(existing)
                except (OSError, ValueError):
                    pass
                with self.engine.ego.lock:
                    identity_data.update({
                        "evolved_insight": self.engine.ego.evolved_insight,
                        "actionable_lessons": self.engine.ego.actionable_lessons,
                        "pending_identity_insight": getattr(
                            self.engine.ego, "pending_identity_insight", ""
                        ),
                        "last_reflected": getattr(
                            self.engine.ego, "last_identity_reflection", time.time()
                        ),
                    })
                from core.utils import atomic_write_json
                atomic_write_json("identity.json", identity_data)
                print(f"{Fore.GREEN}💾 [IDENTITY SYNC]: Bản sắc và bài học đã được đồng bộ hóa vĩnh viễn.{Style.RESET_ALL}")
            except MemoryStoreError:
                raise
            except Exception as exc:
                from core.logger import get_logger
                get_logger("memory.ops").warning(
                    "Identity state sync failed cause_type=%s",
                    type(exc).__name__,
                )
                    
        except MemoryStoreError as exc:
            from core.logger import get_logger
            with self.engine.ego.lock:
                self.engine.ego.evolved_insight = previous_identity
                self.engine.ego.actionable_lessons = previous_lessons
                if hasattr(self.engine.ego, "pending_identity_insight"):
                    self.engine.ego.pending_identity_insight = previous_pending
            get_logger("memory.ops").error(
                "Identity evolution persistence failed operation=%s cause_type=%s",
                exc.operation,
                exc.cause_type,
            )
            raise
        except Exception as exc:
            from core.logger import get_logger
            with self.engine.ego.lock:
                self.engine.ego.evolved_insight = previous_identity
                self.engine.ego.actionable_lessons = previous_lessons
                if hasattr(self.engine.ego, "pending_identity_insight"):
                    self.engine.ego.pending_identity_insight = previous_pending
            get_logger("memory.ops").error(
                "Identity evolution failed cause_type=%s",
                type(exc).__name__,
            )

    def _tool_workshop_phase(self):
        """Phase 4 Self-Evolution: Aura tự học và viết code tạo Tool mới khi phát hiện lỗ hổng kỹ năng."""
        if not getattr(Config, "ALLOW_DYNAMIC_SKILLS", False):
            return

        with self.engine.stm_lock:
            buffer_snapshot = list(self.engine.short_term_buffer)
        if not buffer_snapshot:
            return

        history_str = "\n".join(buffer_snapshot)
        
        # Bước 1: Nhận diện lỗ hổng kỹ năng
        gap_prompt = f"""
        Bạn là Aura. Hãy xem xét lịch sử trò chuyện gần đây và xác định xem người dùng có yêu cầu bạn làm một việc gì đó mà bạn CHƯA CÓ CÔNG CỤ (Tool) để thực hiện không?
        Nếu có, hãy mô tả công cụ đó. Nếu không, trả về 'NONE'.
        
        LỊCH SỬ TRÒ CHUYỆN:
        {history_str}
        
        CÁC CÔNG CỤ HIỆN CÓ:
        {self.engine.skills.get_prompt_instructions()}
        
        Trả về DUY NHẤT định dạng JSON:
        {{
            "has_gap": true | false,
            "tool_name": "tên_công_cụ_ngắn_gọn (snake_case)",
            "description": "mô tả chi tiết chức năng",
            "required_logic": "mô tả logic cần thiết"
        }}
        """
        try:
            raw_gap, _ = self.engine.llm.generate_text(gap_prompt, temperature=0.3, bio_throttle=False)
            gap_data = json.loads(raw_gap.strip().replace("```json", "").replace("```", "").strip())
            
            if not gap_data.get("has_gap"):
                return
                
            from core import skills as dynamic_skills

            tool_name = gap_data.get("tool_name")
            valid_name, invalid_reason = dynamic_skills.validate_dynamic_skill_name(tool_name)
            if not valid_name:
                print(f"{Fore.RED}   ❌ Tool Workshop từ chối tên không an toàn: {invalid_reason}.{Style.RESET_ALL}")
                return
            print(f"\n{Fore.LIGHTBLUE_EX}🛠️ [TOOL WORKSHOP]: Aura nhận thấy mình thiếu công cụ: {tool_name}. Đang tự học cách viết code...{Style.RESET_ALL}")
            
            # Bước 2: Viết code Python cho Tool
            code_prompt = f"""
            Hãy viết một hàm Python tên là `{tool_name}` để thực hiện chức năng sau: {gap_data['description']}
            Hàm phải nhận vào một tham số chuỗi `args` và trả về một chuỗi kết quả.
            
            QUY TẮC:
            1. Chỉ được import các module sau: {", ".join(sorted(dynamic_skills.DYNAMIC_SKILL_ALLOWED_IMPORTS))}.
            2. Code phải hoàn chỉnh, sạch sẽ và có docstring.
            3. Xuất thêm 2 biến hằng số: `DESCRIPTION` (mô tả tool) và `USAGE` (định dạng dùng tool, vd: "ACTION: {tool_name} | <input>").
            
            TRẢ VỀ DUY NHẤT MÃ NGUỒN PYTHON. KHÔNG GIẢI THÍCH.
            """
            
            python_code, _ = self.engine.llm.generate_text(code_prompt, temperature=0.1, bio_throttle=False)
            python_code = python_code.strip().replace("```python", "").replace("```", "").strip()
            
            source_is_safe, block_reason = dynamic_skills.validate_dynamic_skill_source(python_code)
            if not source_is_safe:
                print(f"{Fore.RED}   ❌ Code Aura viết không an toàn: {block_reason}. Hủy bỏ việc tự học.{Style.RESET_ALL}")
                return

            import ast
            source_tree = ast.parse(python_code)
            if not any(
                isinstance(node, ast.FunctionDef) and node.name == tool_name
                for node in source_tree.body
            ):
                print(f"{Fore.RED}   ❌ Code không định nghĩa hàm '{tool_name}'. Hủy bỏ việc tự học.{Style.RESET_ALL}")
                return

            # Lưu vào quarantine. LLM-generated code is never activated
            # automatically; an operator must review and promote it manually.
            try:
                dynamic_dir = dynamic_skills.resolve_dynamic_skill_candidates_dir()
            except ValueError as exc:
                print(f"{Fore.RED}   ❌ Tool Workshop từ chối thư mục quarantine: {exc}.{Style.RESET_ALL}")
                return
            dynamic_dir.mkdir(parents=True, exist_ok=True)
            file_path = (dynamic_dir / f"{tool_name}.py").resolve()
            if file_path.parent != dynamic_dir:
                print(f"{Fore.RED}   ❌ Tool Workshop từ chối đường dẫn nằm ngoài thư mục kỹ năng.{Style.RESET_ALL}")
                return

            try:
                with file_path.open("x", encoding="utf-8") as skill_file:
                    skill_file.write(python_code)
            except FileExistsError:
                print(f"{Fore.YELLOW}   ⚠️ Kỹ năng '{tool_name}' đã tồn tại; không ghi đè.{Style.RESET_ALL}")
                return
                
            print(f"{Fore.GREEN}   ✅ [CANDIDATE CREATED]: Đã lưu bản nháp để review: {file_path}{Style.RESET_ALL}")
            print(f"{Fore.CYAN}   🔒 Kỹ năng chưa được kích hoạt; operator phải duyệt và promote thủ công.{Style.RESET_ALL}")
            
        except Exception as e:
            from core.logger import get_logger
            get_logger("memory.ops").error(f"Lỗi Tool Workshop: {e}", exc_info=True)

    def _calibration_phase(self):
        """Phase 1 Self-Evolution: Aura tự hiệu chỉnh tham số sinh học dựa trên phản tư."""
        with self.engine.stm_lock:
            buffer_snapshot = list(self.engine.short_term_buffer)
        if not buffer_snapshot:
            return

        print(f"\n{Fore.LIGHTBLUE_EX}⚖️ [CALIBRATION ENGINE]: Aura đang tự kiểm tra các chỉ số bản thân...{Style.RESET_ALL}")
        
        history_str = "\n".join(buffer_snapshot)
        current_state = {
            "mood": self.engine.ego.mood,
            "stress": self.engine.ego.stress,
            "fatigue": self.engine.ego.fatigue,
            "integrity": self.engine.ego.integrity,
            "resilience": self.engine.ego.resilience,
            "overrides": self.engine.ego.calibrated_overrides
        }

        prompt = f"""
        Bạn là hệ thống tự giám sát của Aura. Hãy phân tích trạng thái và tương tác trong ngày:
        --- TRẠNG THÁI HIỆN TẠI ---
        {json.dumps(current_state)}
        
        --- LỊCH SỬ TRÒ CHUYỆN ---
        {history_str}
        
        Nhiệm vụ: 
        1. Đánh giá xem Aura có đang quá nhạy cảm với stress không? 
        2. Có cần điều chỉnh các ngưỡng (thresholds) để hoạt động hiệu quả hơn không?
        
        CÁC THAM SỐ CÓ THỂ CHỈNH (giá trị từ 0.0 đến 2.0):
        - stress_critical: Ngưỡng hoảng loạn (mặc định ~0.9)
        - fatigue_critical: Ngưỡng kiệt sức (mặc định ~1.0)
        - resilience: Khả năng chống chịu (mặc định ~0.0-1.0)
        
        TRẢ VỀ DUY NHẤT ĐỊNH DẠNG JSON:
        {{
            "analysis": "Phân tích ngắn gọn",
            "updates": {{
                "tên_tham_số": <giá trị mới>
            }}
        }}
        """
        try:
            generated = self.engine.llm.generate_text(prompt, temperature=0.2, bio_throttle=False)
            raw_response = generated[0] if isinstance(generated, tuple) else generated
        except Exception as exc:
            raise CalibrationError("inference", exc) from None

        try:
            updates = _parse_calibration_payload(raw_response)
        except Exception as exc:
            raise CalibrationError("validation", exc) from None

        if not updates:
            return

        try:
            committed = self._commit_calibration_updates(updates)
        except BaseException as exc:
            if not isinstance(exc, Exception):
                raise
            raise CalibrationError("commit", exc) from None

        for attribute, value in committed.items():
            print(
                f"{Fore.GREEN}   ⚙️ [PARAM UPDATED]: "
                f"{attribute} -> {value:.2f}{Style.RESET_ALL}"
            )

    def _commit_calibration_updates(self, updates):
        """Use the production commit API, with rollback for legacy fakes."""

        normalized = validate_calibration_updates(updates)
        commit = getattr(self.engine.ego, "commit_calibration", None)
        if callable(commit):
            return commit(normalized)
        if not normalized:
            return normalized

        ego = self.engine.ego
        lock = getattr(ego, "lock", None)
        save_state = getattr(ego, "save_state", None)
        if lock is None or not callable(save_state):
            raise TypeError("ego must implement commit_calibration")

        # Lightweight integrations historically exposed save_state() as a
        # lock-owning method. Never invoke it while holding a plain Lock.
        with lock:
            if type(getattr(ego, "calibrated_overrides", None)) is not dict:
                raise TypeError("calibrated_overrides must be an object")
            previous_attributes = {
                attribute: getattr(ego, attribute)
                for attribute in normalized
            }
            overrides = ego.calibrated_overrides
            previous_overrides = dict(overrides)
            try:
                for attribute, value in normalized.items():
                    setattr(ego, attribute, value)
                    overrides[attribute] = value
            except BaseException:
                for attribute, value in previous_attributes.items():
                    setattr(ego, attribute, value)
                overrides.clear()
                overrides.update(previous_overrides)
                raise

        try:
            save_state()
        except BaseException:
            with lock:
                for attribute, value in previous_attributes.items():
                    setattr(ego, attribute, value)
                overrides.clear()
                overrides.update(previous_overrides)
            raise
        return normalized

    def _belief_evolution_phase(self):
        """Phase 2 Self-Evolution: Aura tự rà soát và giải quyết mâu thuẫn trong hệ thống niềm tin cốt lõi."""
        try:
            mems = self.engine.memory.get_all()
        except MemoryStoreError as exc:
            from core.logger import get_logger
            get_logger("memory.ops").error(
                "Belief evolution read failed operation=%s cause_type=%s",
                exc.operation,
                exc.cause_type,
            )
            raise
        memories_by_id = {str(memory.id): memory for memory in mems}

        # A prior merge may have committed its deterministic replacement and
        # then failed deleting the old beliefs. Finish that exact deletion
        # before asking the LLM again.
        belief_manifests = [
            trace
            for trace in mems
            if str(getattr(trace, "consolidation_id", "") or "").startswith(
                "belief-"
            )
        ]
        live_intents = {}
        live_merge_children = {}
        saw_live_manifest = False
        for trace in belief_manifests:
            consolidation_id = str(trace.consolidation_id)
            parent_ids = list(
                getattr(trace, "consolidation_parent_ids", []) or []
            )
            provenance_ids = list(
                getattr(trace, "provenance_parent_ids", []) or []
            )
            if (
                not parent_ids
                or any(
                    not isinstance(parent_id, str) or not parent_id
                    for parent_id in parent_ids
                )
                or len(set(parent_ids)) != len(parent_ids)
                or parent_ids != sorted(parent_ids)
                or provenance_ids != parent_ids
                or _memory_policy(trace) is None
                or getattr(trace, "origin_kind", "") != "belief_evolution"
                or getattr(trace, "origin_source", "") != "sleep"
            ):
                return
            existing_parents = [
                memories_by_id[parent_id]
                for parent_id in parent_ids
                if parent_id in memories_by_id
            ]
            if not existing_parents:
                # No deletion remains to authorize. Ignore historical lineage
                # before version-specific validation so a safe legacy record
                # cannot block all future belief evolution forever.
                continue
            saw_live_manifest = True
            expected_count = getattr(
                trace,
                "consolidation_expected_derived_count",
                0,
            )
            is_delete_intent = consolidation_id.startswith("belief-delete:")
            is_merge_child = consolidation_id.startswith("belief-merge:")
            if is_delete_intent:
                expected_intent_id = _belief_delete_intent_id(parent_ids)
                if (
                    str(trace.id) != expected_intent_id
                    or consolidation_id != f"belief-delete:{expected_intent_id}"
                    or not _has_memory_type(trace, MemoryType.SEMANTIC)
                    or expected_count not in {1, 2}
                    or (
                        expected_count == 1
                        and trace.content != _BELIEF_DELETE_INTENT_CONTENT
                    )
                    or (
                        expected_count == 2
                        and _belief_merge_content_from_intent(trace) is None
                    )
                ):
                    return
            elif is_merge_child:
                # A merge child is useful lineage, never deletion authority.
                if (
                    expected_count not in {1, 2}
                    or not _is_canonical_belief_merge_child(
                        trace,
                        parent_ids,
                    )
                ):
                    return
            else:
                return
            manifest_policy = _homogeneous_policy(existing_parents)
            if (
                manifest_policy is None
                or _memory_policy(trace) != manifest_policy
                or any(not _is_belief_source(parent) for parent in existing_parents)
            ):
                return
            group_key = tuple(parent_ids)
            remaining_parent_ids = {
                str(parent.id) for parent in existing_parents
            }
            if is_delete_intent:
                if group_key in live_intents:
                    return
                live_intents[group_key] = (
                    trace,
                    manifest_policy,
                    remaining_parent_ids,
                )
            else:
                live_merge_children.setdefault(group_key, []).append((
                    trace,
                    manifest_policy,
                    remaining_parent_ids,
                ))

        live_group_keys = sorted(
            set(live_intents).union(live_merge_children)
        )
        claimed_parent_ids: set[str] = set()
        for group_key in live_group_keys:
            group_parent_ids = set(group_key)
            if claimed_parent_ids.intersection(group_parent_ids):
                return
            claimed_parent_ids.update(group_parent_ids)
            if len(live_merge_children.get(group_key, [])) > 1:
                return

        recovery_by_policy: dict[
            tuple[str, str],
            list[MemoryTrace],
        ] = {}
        completed_groups = []
        for group_key in live_group_keys:
            intent_entry = live_intents.get(group_key)
            merge_entries = live_merge_children.get(group_key, [])
            parent_ids = list(group_key)
            if intent_entry is not None:
                intent, intent_policy, remaining_parent_ids = intent_entry
                intent_expected_count = (
                    intent.consolidation_expected_derived_count
                )
                if intent_expected_count == 1:
                    if merge_entries:
                        return
                else:
                    merge_content = _belief_merge_content_from_intent(intent)
                    if merge_content is None:
                        return
                    expected_child = _build_belief_merge_child(
                        parent_ids,
                        intent_policy,
                        merge_content,
                    )
                    if merge_entries:
                        (
                            merge_child,
                            merge_policy,
                            merge_remaining_ids,
                        ) = merge_entries[0]
                        if (
                            merge_policy != intent_policy
                            or merge_remaining_ids != remaining_parent_ids
                            or not _durable_trace_matches(
                                merge_child,
                                expected_child,
                            )
                        ):
                            return
                    else:
                        recovery_by_policy.setdefault(
                            intent_policy,
                            [],
                        ).append(expected_child)
                completed_groups.append((
                    intent_policy,
                    remaining_parent_ids,
                ))
                continue

            if not merge_entries:
                continue
            merge_child, merge_policy, remaining_parent_ids = merge_entries[0]
            if merge_child.consolidation_expected_derived_count != 2:
                # Old pre-intent-per-group manifests cannot safely authorize a
                # reconstructed destructive operation.
                continue
            merge_content = _belief_merge_content_from_child(merge_child)
            if merge_content is None:
                return
            expected_intent = _build_belief_delete_intent(
                parent_ids,
                merge_policy,
                merge_content=merge_content,
            )
            recovery_by_policy.setdefault(merge_policy, []).append(
                expected_intent
            )
            completed_groups.append((merge_policy, remaining_parent_ids))

        if recovery_by_policy:
            try:
                recovery_records = []
                for policy, records in sorted(recovery_by_policy.items()):
                    with memory_context_scope(_write_context_for_scope(
                        policy[0],
                        origin_kind="belief_evolution",
                        origin_source="sleep",
                    )):
                        self.engine.memory.add_memories(records)
                    recovery_records.extend(records)
                persisted_by_id = {
                    str(trace.id): trace
                    for trace in self.engine.memory.get_all()
                }
                if any(
                    not _durable_trace_matches(
                        persisted_by_id.get(str(expected.id)),
                        expected,
                    )
                    for expected in recovery_records
                ):
                    return
            except MemoryStoreError as exc:
                from core.logger import get_logger
                get_logger("memory.ops").error(
                    "Belief retry repair failed operation=%s cause_type=%s",
                    exc.operation,
                    exc.cause_type,
                )
                raise

        pending_by_policy: dict[tuple[str, str], set[str]] = {}
        for policy, remaining_parent_ids in completed_groups:
            pending_by_policy.setdefault(policy, set()).update(
                remaining_parent_ids
            )

        if pending_by_policy:
            try:
                for policy, pending_parent_ids in sorted(
                    pending_by_policy.items()
                ):
                    with memory_context_scope(_write_context_for_scope(
                        policy[0],
                        origin_kind="belief_retry",
                        origin_source="sleep",
                    )):
                        self.engine.memory.remove_many(
                            sorted(pending_parent_ids)
                        )
            except MemoryStoreError as exc:
                from core.logger import get_logger
                get_logger("memory.ops").error(
                    "Belief merge retry failed operation=%s cause_type=%s",
                    exc.operation,
                    exc.cause_type,
                )
                raise
            return
        if saw_live_manifest:
            # Never ask the LLM for a second plan while any incomplete durable
            # operation still references live parents.
            return

        # Lọc các niềm tin (Core/Semantic có chứa từ 'Belief')
        beliefs = sorted(
            [
                memory for memory in mems
                if memory.type in [MemoryType.CORE, MemoryType.SEMANTIC]
                and "Belief" in memory.content
                and not str(
                    getattr(memory, "consolidation_id", "") or ""
                ).startswith("belief-delete:")
            ],
            key=lambda memory: (float(memory.created_at), str(memory.id)),
        )
        
        if len(beliefs) < 2:
            return
        belief_policy = _homogeneous_policy(beliefs)
        if belief_policy is None:
            # Never expose a mixed owner/agent batch to the mutation LLM. A
            # derived belief and its delete intent need one unambiguous policy.
            return

        print(f"\n{Fore.LIGHTBLUE_EX}🧩 [BELIEF EVOLUTION]: Aura đang rà soát tính nhất quán của {len(beliefs)} niềm tin...{Style.RESET_ALL}")
        
        # Nhóm các niềm tin theo cụm để LLM dễ xử lý (tránh quá tải context)
        belief_list_str = "\n".join([f"- [{i}] {m.content}" for i, m in enumerate(beliefs)])
        
        prompt = f"""
        Bạn là hệ thống logic nội tại của Aura. Hãy rà soát danh sách các niềm tin cốt lõi sau đây và tìm ra các cặp NIỀM TIN MÂU THUẪN HOẶC TRÙNG LẶP.
        
        DANH SÁCH NIỀM TIN:
        {belief_list_str}
        
        Nhiệm vụ:
        1. Tìm các cặp (hoặc nhóm) niềm tin đang đấu đá lẫn nhau (ví dụ: một cái bảo 'Tin người', một cái bảo 'Không tin ai').
        2. Quyết định xem nên GIỮ CÁI NÀO (KEPT), XÓA CÁI NÀO (DELETED) hoặc HỢP NHẤT chúng thành một niềm tin trưởng thành hơn (MERGED).
        
        TRẢ VỀ DUY NHẤT ĐỊNH DẠNG JSON:
        {{
            "analysis": "Phân tích ngắn gọn về mâu thuẫn",
            "resolutions": [
                {{"type": "DELETE", "indices": [i1, i2], "reason": "Lý do xóa"}},
                {{"type": "MERGE", "indices": [i1, i2], "new_content": "Câu niềm tin mới", "reason": "Lý do hợp nhất"}}
            ]
        }}
        Nếu không có mâu thuẫn, trả về {{"analysis": "Nhất quán", "resolutions": []}}.
        """
        try:
            raw_res, _ = self.engine.llm.generate_text(prompt, temperature=0.1, model_override=Config.DEEP_MODEL_NAME, bio_throttle=False)
            json_str = raw_res.strip().replace("```json", "").replace("```", "").strip()
            data = json.loads(json_str)
            
            resolutions = data.get("resolutions", [])
            if not isinstance(resolutions, list) or not resolutions:
                return

            print(f"{Fore.CYAN}   📝 Phân tích nội tại: {data.get('analysis')}{Style.RESET_ALL}")

            # ── Risk #4 Fix: Snapshot memories TRƯỚC KHI mutate ────────────────
            # Lưu bản sao JSON vào outputs/memory_versions/belief_<timestamp>.json
            # Có thể khôi phục bằng cách đọc file này nếu LLM hallucinate kết quả xấu.
            try:
                import datetime
                version_dir = os.path.join(
                    getattr(Config, 'OUTPUT_DIR', 'outputs'), "memory_versions"
                )
                os.makedirs(version_dir, exist_ok=True)
                ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                version_file = os.path.join(version_dir, f"belief_{ts}.json")
                snapshot = [
                    {"id": b.id, "content": b.content, "type": str(b.type),
                     "valence": b.valence, "importance": b.importance}
                    for b in beliefs
                ]
                with open(version_file, "w", encoding="utf-8") as vf:
                    import json as _json
                    _json.dump({"snapshot_at": ts, "memories": snapshot,
                                "reason": data.get("analysis", "")}, vf,
                               ensure_ascii=False, indent=2)
                print(f"{Fore.LIGHTBLACK_EX}   💾 [MEM VERSION]: Đã lưu bản sao {len(beliefs)} ký ức vào {version_file}{Style.RESET_ALL}")
            except Exception as exc:
                from core.logger import get_logger
                get_logger("memory.ops").warning(
                    "Belief snapshot failed cause_type=%s",
                    type(exc).__name__,
                )
            # ────────────────────────────────────────────────────────────────────

            normalized_resolutions = []
            for res in resolutions:
                if not isinstance(res, dict):
                    continue
                res_type = str(res.get("type", "")).upper()
                indices = res.get("indices", [])
                if res_type not in {"DELETE", "MERGE"} or not isinstance(indices, list):
                    continue
                valid_indices = sorted({
                    index
                    for index in indices
                    if isinstance(index, int)
                    and not isinstance(index, bool)
                    and 0 <= index < len(beliefs)
                })
                new_content = res.get("new_content", "")
                if not isinstance(new_content, str):
                    new_content = ""
                new_content = new_content.strip()
                if res_type == "MERGE" and (
                    len(valid_indices) < 2 or not new_content
                ):
                    continue
                if res_type == "DELETE" and not valid_indices:
                    continue
                normalized_resolutions.append(
                    (res_type, valid_indices, new_content)
                )

            # Canonical ordering and disjoint source groups make the accepted
            # mutation independent of the LLM's resolution ordering.
            normalized_resolutions.sort(
                key=lambda item: (
                    0 if item[0] == "MERGE" else 1,
                    tuple(item[1]),
                    item[2],
                )
            )
            claimed_ids = set()
            ids_to_delete = set()
            write_by_id = {}
            accepted_groups = []
            for res_type, indices, new_content in normalized_resolutions:
                parent_ids = sorted(str(beliefs[index].id) for index in indices)
                if claimed_ids.intersection(parent_ids):
                    continue
                claimed_ids.update(parent_ids)
                ids_to_delete.update(parent_ids)
                accepted_groups.append((res_type, parent_ids, new_content))
                if res_type != "MERGE":
                    continue
                merge_child = _build_belief_merge_child(
                    parent_ids,
                    belief_policy,
                    new_content,
                )
                merge_key = str(merge_child.id)
                if merge_key in write_by_id:
                    # UUID derivation is deterministic, but an operation plan
                    # must still fail closed if two distinct groups ever map
                    # to one durable record ID.
                    return
                write_by_id[merge_key] = merge_child

            if not ids_to_delete:
                return
            sorted_delete_ids = sorted(ids_to_delete)
            for res_type, parent_ids, new_content in accepted_groups:
                intent = _build_belief_delete_intent(
                    parent_ids,
                    belief_policy,
                    merge_content=(
                        new_content if res_type == "MERGE" else None
                    ),
                )
                intent_key = str(intent.id)
                if intent_key in write_by_id:
                    return
                write_by_id[intent_key] = intent
            write_batch = [write_by_id[key] for key in sorted(write_by_id)]
            with memory_context_scope(_write_context_for_scope(
                belief_policy[0],
                origin_kind="belief_evolution",
                origin_source="sleep",
            )):
                self.engine.memory.add_memories(write_batch)
                persisted_by_id = {
                    str(trace.id): trace
                    for trace in self.engine.memory.get_all()
                }
                if any(
                    not _durable_trace_matches(
                        persisted_by_id.get(str(expected.id)),
                        expected,
                    )
                    for expected in write_batch
                ):
                    return
                self.engine.memory.remove_many(sorted_delete_ids)
                
        except MemoryStoreError as exc:
            from core.logger import get_logger
            get_logger("memory.ops").error(
                "Belief evolution persistence failed operation=%s cause_type=%s",
                exc.operation,
                exc.cause_type,
            )
            raise
        except Exception as exc:
            from core.logger import get_logger
            get_logger("memory.ops").error(
                "Belief evolution failed cause_type=%s",
                type(exc).__name__,
            )
