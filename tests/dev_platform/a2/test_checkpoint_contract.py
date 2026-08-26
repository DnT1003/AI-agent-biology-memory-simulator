from __future__ import annotations

from pathlib import Path
from types import MappingProxyType
from unittest.mock import patch
import os
import stat
import subprocess
import sys
import threading
import textwrap
from types import SimpleNamespace

import pytest

from core.contracts import (CanonicalJSONError, EnvelopeValidationError,
    MAX_CANONICAL_DEPTH, MAX_CANONICAL_JSON_BYTES,
    MAX_SIGNED_INT64, PersistedEnvelope, canonical_json_bytes,
    canonical_json_sha256, parse_canonical_json_bytes)
from core.schema_registry import (SchemaRegistry, SchemaRegistrationError,
    SchemaValidationError)
from core.settings_manager import SettingsManager
from core.state_store import (ArtifactRecord, CurrentInspection, CurrentPointer,
    DurabilityLevel, FailureContext, GenerationInspection, GenerationManifest,
    GenerationReference, GenerationSnapshot, InspectionStatus, InspectionIssue, OrphanTemp,
    PreparedGeneration, PublicationResult, StateStore,
    StateStoreOperation, StateStorePreconditionError, StateStoreIOError,
    StateCorruptionError, StateStoreError, TempKind, UncommittedGenerationError, FailurePoint,
    StateStoreValidationError)

GENERATION = "g-0123456789abcdef0123456789abcdef"


def registry() -> SchemaRegistry:
    value = SchemaRegistry()
    value.register(schema="aura.settings", version=1, validator=lambda payload: None)
    return value.freeze()


def store(tmp_path: Path) -> StateStore:
    root = tmp_path.resolve()
    return StateStore(state_dir=root / "state", generations_dir=root / "state" / "generations", current_path=root / "state" / "CURRENT", registry=registry())


def envelope() -> PersistedEnvelope[object]:
    return PersistedEnvelope.create(schema="aura.settings", schema_version=1, revision=0, generation=GENERATION, updated_at_ns=0, payload={"provider": "local", "temperature": -0.0})


def test_canonical_golden_and_strict_parser() -> None:
    value = envelope()
    assert value.payload_sha256 == "1f6a6ac66ea642a605d4637027c7b8a961a6a3fe4faed08ece057bb99c645237"
    assert b'"temperature":0.0' in value.to_bytes()
    assert canonical_json_bytes({"x": 1}) != canonical_json_bytes({"x": 1.0})
    with pytest.raises(CanonicalJSONError):
        parse_canonical_json_bytes(b'{"a":1, "b":2}')
    with pytest.raises(CanonicalJSONError):
        parse_canonical_json_bytes(b'{"a":1,"a":2}')


@pytest.mark.parametrize("value", [2**63, -(2**63) - 1, float("nan"), float("inf"), "\ud800"])
def test_canonical_payload_boundaries_raise_envelope_errors(value: object) -> None:
    with pytest.raises(EnvelopeValidationError):
        PersistedEnvelope.create(schema="aura.settings", schema_version=1, revision=0, generation=GENERATION, updated_at_ns=0, payload=value)


def test_canonical_int64_float_unicode_and_noncanonical_boundaries() -> None:
    assert canonical_json_bytes({"min": -(2**63), "max": MAX_SIGNED_INT64})
    assert canonical_json_bytes({"nfc": "é"}) != canonical_json_bytes({"nfd": "e\u0301"})
    for data in (b'\xef\xbb\xbf{}', b'{ }', b'{"x":1e0}', b'{"x":01}', b'{"x":1}\n'):
        with pytest.raises(CanonicalJSONError):
            parse_canonical_json_bytes(data)


def test_generation_and_current_are_immutable_and_verifier_gated(tmp_path: Path) -> None:
    target = store(tmp_path)
    prepared = target.prepare_generation(generation=GENERATION, envelopes={"settings": envelope()})
    assert prepared.created is True
    assert target.read_current() is None
    with pytest.raises(UncommittedGenerationError):
        target.publish_committed_generation(prepared.manifest.reference, verifier=type("No", (), {"is_current_committed": lambda self, ref: 1})())
    result = target.publish_committed_generation(prepared.manifest.reference, verifier=type("Yes", (), {"is_current_committed": lambda self, ref: True})())
    assert result.changed is True
    assert target.read_current() == result.pointer
    assert target.prepare_generation(generation=GENERATION, envelopes=MappingProxyType({"settings": envelope()})).created is False


def test_verifier_exception_precedes_current_and_temp_creation(tmp_path: Path) -> None:
    target = store(tmp_path)
    prepared = target.prepare_generation(generation=GENERATION, envelopes={"settings": envelope()})
    class Verifier:
        def is_current_committed(self, reference: object) -> bool:
            raise LookupError("control database unavailable")
    with pytest.raises(LookupError, match="control database unavailable"):
        target.publish_committed_generation(prepared.manifest.reference, verifier=Verifier())
    assert not list(target.state_dir.glob(".tmp-CURRENT-*"))
    assert target.read_current() is None


def test_orphan_discovery_ignores_nonmatching_and_rejects_wrong_type(tmp_path: Path) -> None:
    target = store(tmp_path)
    target._ensure_layout(StateStoreOperation.PREPARE_GENERATION)
    (target.state_dir / "ignore").write_text("x", encoding="utf-8")
    (target.state_dir / (".tmp-CURRENT-" + "0" * 32 + ".tmp")).mkdir()
    with pytest.raises(StateCorruptionError) as caught:
        target.find_orphan_temps()
    # A bad matching orphan is a state corruption, not an ignored filename.
    assert caught.value.issue is InspectionIssue.WRONG_TYPE


def test_state_store_requires_frozen_registry(tmp_path: Path) -> None:
    value = SchemaRegistry()
    with pytest.raises(StateStorePreconditionError):
        StateStore(state_dir=tmp_path.resolve() / "state", generations_dir=tmp_path.resolve() / "state" / "generations", current_path=tmp_path.resolve() / "state" / "CURRENT", registry=value)


def test_windows_directory_durability_oracle(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    target = store(tmp_path)
    monkeypatch.setattr("core.state_store.os.name", "nt")
    assert target._flush_dir(tmp_path.resolve(), StateStoreOperation.PREPARE_GENERATION) is DurabilityLevel.DIRECTORY_ENTRY_UNCONFIRMED


def test_registry_freeze_versions_and_evolution_are_pure() -> None:
    value = SchemaRegistry()
    value.register(schema="aura.settings", version=2, validator=lambda payload: None, evolve_from_previous=lambda payload: {"v": 2})
    value.register(schema="aura.settings", version=1, validator=lambda payload: None)
    value.freeze()
    assert value.evolve_payload(schema="aura.settings", from_version=1, to_version=2, payload={"v": 1}) == MappingProxyType({"v": 2})
    with pytest.raises(SchemaRegistrationError):
        value.register(schema="aura.settings", version=3, validator=lambda payload: None, evolve_from_previous=lambda payload: payload)


def test_registry_normalizes_validator_exceptions() -> None:
    value = SchemaRegistry()
    value.register(schema="aura.settings", version=1, validator=lambda payload: (_ for _ in ()).throw(RuntimeError("bad")))
    value.freeze()
    with pytest.raises(SchemaValidationError):
        value.validate_envelope(envelope())


def test_inspection_missing_generation_has_exact_truth_table(tmp_path: Path) -> None:
    target = store(tmp_path)
    reference = target.__class__.__dict__["prepare_generation"].__globals__["GenerationReference"](GENERATION, "0" * 64)
    inspected = target.inspect_generation(reference)
    assert inspected.status.value == "missing"
    assert inspected.snapshot is inspected.issue is inspected.error is None


@pytest.mark.parametrize("point", list(FailurePoint))
def test_all_eleven_failure_points_have_distinct_dotted_values(point: FailurePoint) -> None:
    assert "." in point.value
    assert len({item.value for item in FailurePoint}) == 11


def test_zero_write_progress_is_io_failure(tmp_path: Path) -> None:
    target = store(tmp_path)
    target._ensure_layout(StateStoreOperation.PREPARE_GENERATION)
    with patch("core.state_store.os.write", return_value=0):
        with pytest.raises(StateStoreIOError) as caught:
            target._write_file(target.state_dir / "x", b"x", StateStoreOperation.PREPARE_GENERATION)
    assert caught.value.issue is InspectionIssue.IO_FAILURE


def test_constructor_is_lexical_and_rejects_dot_components_without_lstat(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    value = registry()
    with patch("core.state_store.os.lstat") as lstat:
        with pytest.raises(StateStorePreconditionError):
            StateStore(state_dir=tmp_path / "state" / ".." / "state", generations_dir=tmp_path / "state" / "generations", current_path=tmp_path / "state" / "CURRENT", registry=value)
    lstat.assert_not_called()


def test_current_open_handle_accepts_atomic_old_pointer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = store(tmp_path)
    prepared = target.prepare_generation(generation=GENERATION, envelopes={"settings": envelope()})
    verifier = type("Yes", (), {"is_current_committed": lambda self, ref: True})()
    target.publish_committed_generation(prepared.manifest.reference, verifier=verifier)
    original_meta = target._meta
    calls = 0
    def swapped(path: Path, operation: StateStoreOperation, **kwargs: object):
        nonlocal calls
        calls += 1
        return original_meta(path, operation, **kwargs)
    monkeypatch.setattr(target, "_meta", swapped)
    assert target.read_current() is not None
    assert calls >= 1


def test_validator_and_evolution_callback_registry_errors_are_normalized() -> None:
    value = SchemaRegistry()
    value.register(schema="aura.settings", version=1, validator=lambda payload: (_ for _ in ()).throw(SchemaValidationError("callback")))
    value.freeze()
    with pytest.raises(SchemaValidationError) as validation:
        value.validate_envelope(envelope())
    assert isinstance(validation.value.__cause__, SchemaValidationError)
    evolving = SchemaRegistry()
    evolving.register(schema="aura.settings", version=1, validator=lambda payload: None)
    evolving.register(schema="aura.settings", version=2, validator=lambda payload: None, evolve_from_previous=lambda payload: (_ for _ in ()).throw(SchemaValidationError("callback")))
    evolving.freeze()
    from core.schema_registry import SchemaEvolutionError
    with pytest.raises(SchemaEvolutionError) as evolution:
        evolving.evolve_payload(schema="aura.settings", from_version=1, to_version=2, payload={})
    assert isinstance(evolution.value.__cause__, SchemaValidationError)


def test_input_mapping_is_snapshotted_before_write(tmp_path: Path) -> None:
    target = store(tmp_path)
    values = {"settings": envelope()}
    prepared = target.prepare_generation(generation=GENERATION, envelopes=values)
    values["other"] = envelope()
    snapshot = target.read_generation(prepared.manifest.reference)
    assert tuple(snapshot.envelopes) == ("settings",)


def test_current_retries_a_real_pre_open_atomic_replacement(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """CURRENT alone accepts an old/new complete pointer at the lstat/open seam."""
    target = store(tmp_path)
    first = target.prepare_generation(generation=GENERATION, envelopes={"settings": envelope()})
    second_generation = "g-fedcba98765432100123456789abcdef"
    second_envelope = PersistedEnvelope.create(schema="aura.settings", schema_version=1, revision=1,
        generation=second_generation, updated_at_ns=1, payload={"provider": "local"})
    second = target.prepare_generation(generation=second_generation, envelopes={"settings": second_envelope})
    verifier = type("Yes", (), {"is_current_committed": lambda self, ref: True})()
    target.publish_committed_generation(first.manifest.reference, verifier=verifier)
    replacement = CurrentPointer(second.manifest.reference, canonical_json_sha256({
        "format": "aura.state-current.v1", "generation": second_generation,
        "manifest_sha256": second.manifest.reference.manifest_sha256,
    }))
    staged = target.state_dir / ".swap-CURRENT"
    staged.write_bytes(replacement.to_bytes())
    real_open = __import__("os").open
    swapped = False
    def open_after_lstat(path: str, flags: int, *args: object) -> int:
        nonlocal swapped
        if not swapped and str(path).endswith("CURRENT"):
            swapped = True
            __import__("os").replace(staged, target.current_path)
        return real_open(path, flags, *args)
    monkeypatch.setattr("core.state_store.os.open", open_after_lstat)
    assert target.read_current() == replacement
    assert swapped is True


def test_generation_file_identity_change_at_pre_open_boundary_remains_corrupt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = store(tmp_path)
    prepared = target.prepare_generation(generation=GENERATION, envelopes={"settings": envelope()})
    artifact = target.generations_dir / GENERATION / "settings.json"
    staged = target.state_dir / "replacement.json"
    staged.write_bytes(artifact.read_bytes())
    real_open = __import__("os").open
    swapped = False
    def replace_generation_file(path: str, flags: int, *args: object) -> int:
        nonlocal swapped
        if not swapped and str(path).endswith("settings.json"):
            swapped = True
            __import__("os").replace(staged, artifact)
        return real_open(path, flags, *args)
    monkeypatch.setattr("core.state_store.os.open", replace_generation_file)
    with pytest.raises(StateCorruptionError) as caught:
        target.read_generation(prepared.manifest.reference)
    assert caught.value.issue is InspectionIssue.IDENTITY_CHANGED


def test_prepare_plan_serializes_each_input_envelope_once_and_writes_that_plan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = store(tmp_path)
    value = envelope()
    original = PersistedEnvelope.to_bytes
    calls = 0
    def counted(self: PersistedEnvelope[object]) -> bytes:
        nonlocal calls
        if self is value:
            calls += 1
            if calls > 1:
                return b'{"mutated":true}'
        return original(self)
    monkeypatch.setattr(PersistedEnvelope, "to_bytes", counted)
    target.prepare_generation(generation=GENERATION, envelopes={"settings": value})
    assert calls == 1


def test_self_hash_diagnoses_are_not_reframed_as_invalid_framing(tmp_path: Path) -> None:
    target = store(tmp_path)
    prepared = target.prepare_generation(generation=GENERATION, envelopes={"settings": envelope()})
    manifest_path = target.generations_dir / GENERATION / "MANIFEST.json"
    raw = parse_canonical_json_bytes(manifest_path.read_bytes())
    changed = dict(raw)
    changed["revision"] = 1
    manifest_path.write_bytes(canonical_json_bytes(changed))
    inspected = target.inspect_generation(prepared.manifest.reference)
    assert inspected.status is InspectionStatus.CORRUPT
    assert inspected.issue is InspectionIssue.CHECKSUM_MISMATCH
    assert inspected.error is not None and inspected.error.issue is InspectionIssue.CHECKSUM_MISMATCH


def test_inspection_and_result_dtos_reject_invalid_truth_table_combinations(tmp_path: Path) -> None:
    target = store(tmp_path)
    reference = GenerationReference(GENERATION, "0" * 64)
    pointer = CurrentPointer(reference, canonical_json_sha256({"format": "aura.state-current.v1", "generation": GENERATION, "manifest_sha256": "0" * 64}))
    assert CurrentInspection(InspectionStatus.MISSING, None, None, None).status is InspectionStatus.MISSING
    assert CurrentInspection(InspectionStatus.VALID, pointer, None, None).pointer == pointer
    assert GenerationInspection(InspectionStatus.MISSING, None, None, None).status is InspectionStatus.MISSING
    with pytest.raises(StateStoreValidationError):
        CurrentInspection(InspectionStatus.VALID, None, None, None)
    with pytest.raises(StateStoreValidationError):
        GenerationInspection(InspectionStatus.CORRUPT, None, InspectionIssue.CHECKSUM_MISMATCH, StateStoreIOError("x", operation=StateStoreOperation.READ_GENERATION))
    orphan_path = target.state_dir / (".tmp-CURRENT-" + "0" * 32 + ".tmp")
    assert OrphanTemp(orphan_path, TempKind.CURRENT_FILE, None).path == orphan_path
    with pytest.raises(StateStoreValidationError):
        OrphanTemp(orphan_path, TempKind.GENERATION_DIRECTORY, GENERATION)
    with pytest.raises(StateStoreValidationError):
        FailureContext(FailurePoint.PREPARE_AFTER_ARTIFACT_FSYNC, GENERATION, target.state_dir / "wrong.json", "settings")


def test_successful_prepare_and_publish_emit_all_hooks_with_exact_contexts(tmp_path: Path) -> None:
    seen: list[FailureContext] = []
    target = store(tmp_path)
    target.fault_injector = seen.append
    prepared = target.prepare_generation(generation=GENERATION, envelopes={"settings": envelope()})
    target.publish_committed_generation(prepared.manifest.reference,
        verifier=type("Yes", (), {"is_current_committed": lambda self, ref: True})())
    assert [item.point for item in seen] == list(FailurePoint)
    assert all(item.generation == GENERATION and item.path.is_absolute() for item in seen)
    artifact = [item for item in seen if item.point is FailurePoint.PREPARE_AFTER_ARTIFACT_FSYNC]
    assert len(artifact) == 1 and artifact[0].artifact == "settings" and artifact[0].path.name == "settings.json"
    assert all(item.artifact is None for item in seen if item is not artifact[0])


def test_idempotent_publication_emits_no_hook_and_hook_exceptions_stay_unwrapped(tmp_path: Path) -> None:
    target = store(tmp_path)
    prepared = target.prepare_generation(generation=GENERATION, envelopes={"settings": envelope()})
    calls = 0
    class Yes:
        def is_current_committed(self, ref: GenerationReference) -> bool:
            nonlocal calls
            calls += 1
            return True
    verifier = Yes()
    target.publish_committed_generation(prepared.manifest.reference, verifier=verifier)
    marker = LookupError("injector identity")
    def explode(_: FailureContext) -> None:
        raise marker
    target.fault_injector = explode
    assert target.publish_committed_generation(prepared.manifest.reference, verifier=verifier).changed is False
    assert calls == 2
    verifier_marker = LookupError("verifier identity")
    class ExplodingVerifier:
        def is_current_committed(self, ref: GenerationReference) -> bool:
            raise verifier_marker
    with pytest.raises(LookupError) as verifier_caught:
        target.publish_committed_generation(prepared.manifest.reference, verifier=ExplodingVerifier())
    assert verifier_caught.value is verifier_marker
    separate = tmp_path / "separate"
    separate.mkdir()
    later = store(separate)
    later.fault_injector = explode
    with pytest.raises(LookupError) as caught:
        later.prepare_generation(generation=GENERATION, envelopes={"settings": envelope()})
    assert caught.value is marker
    assert later.find_orphan_temps() == ()


def test_settings_import_is_write_free_and_first_public_read_lazily_scrubs(tmp_path: Path) -> None:
    output = tmp_path / "subprocess-output"
    environment = dict(os.environ)
    environment["AURA_OUTPUT_DIR"] = str(output)
    environment["PYTHONPATH"] = str(Path.cwd())
    imported = subprocess.run([sys.executable, "-c", "import core.settings_manager"], cwd=Path.cwd(),
        env=environment, text=True, capture_output=True, timeout=20)
    assert imported.returncode == 0, imported.stderr
    assert not (output / "settings.json").exists()

    manager = object.__new__(SettingsManager)
    manager.settings_file = str(tmp_path / "settings.json")
    manager.lock = threading.Lock()
    manager._settings_file_signature = None
    manager._loaded = False
    manager.settings = {"provider": "local", "local_model": "local", "gemini_model": "gemini",
        "openai_model": "openai", "anthropic_model": "anthropic", "system_prompt": "safe",
        "gemini_api_key": "environment-secret", "openai_api_key": "", "anthropic_api_key": ""}
    Path(manager.settings_file).write_text('{"provider":"gemini","gemini_api_key":"disk-secret","unknown":1}', encoding="utf-8")
    assert "disk-secret" in Path(manager.settings_file).read_text(encoding="utf-8")
    assert manager.get("provider") == "gemini"
    assert manager.get("gemini_api_key") == "environment-secret"
    serialized = Path(manager.settings_file).read_text(encoding="utf-8")
    assert "disk-secret" not in serialized and "unknown" not in serialized


def test_complete_failure_context_and_inspection_truth_tables(tmp_path: Path) -> None:
    target = store(tmp_path)
    state, generations = target.state_dir, target.generations_dir
    stage = generations / (".tmp-generation-" + GENERATION + "-" + "0" * 32)
    current_temp = state / (".tmp-CURRENT-" + "0" * 32 + ".tmp")
    valid_paths = {
        FailurePoint.PREPARE_AFTER_STAGE_DIRECTORY: stage,
        FailurePoint.PREPARE_AFTER_ARTIFACT_FSYNC: stage / "settings.json",
        FailurePoint.PREPARE_AFTER_MANIFEST_FSYNC: stage / "MANIFEST.json",
        FailurePoint.PREPARE_AFTER_STAGE_VALIDATION: stage,
        FailurePoint.PREPARE_AFTER_GENERATION_RENAME: generations / GENERATION,
        FailurePoint.PREPARE_AFTER_GENERATIONS_FSYNC: generations,
        FailurePoint.PUBLISH_AFTER_COMMIT_PROOF: state / "CURRENT",
        FailurePoint.PUBLISH_AFTER_POINTER_TEMP_FSYNC: current_temp,
        FailurePoint.PUBLISH_BEFORE_POINTER_REPLACE: state / "CURRENT",
        FailurePoint.PUBLISH_AFTER_POINTER_REPLACE: state / "CURRENT",
        FailurePoint.PUBLISH_AFTER_STATE_FSYNC: state,
    }
    for point, path in valid_paths.items():
        artifact = "settings" if point is FailurePoint.PREPARE_AFTER_ARTIFACT_FSYNC else None
        assert FailureContext(point, GENERATION, path, artifact).path == path
        assert target._failure_context(point, GENERATION, path, artifact).path == path
        wrong_parent = (tmp_path / "wrong-state") / path.relative_to(state)
        # Frozen direct DTOs have no StateStore root; this remains intrinsically valid.
        assert FailureContext(point, GENERATION, wrong_parent, artifact).path == wrong_parent
        with pytest.raises(StateStoreValidationError):
            target._failure_context(point, GENERATION, wrong_parent, artifact)
        with pytest.raises(StateStoreValidationError):
            target._failure_context(point, GENERATION, state / "wrong-basename", artifact)
    with pytest.raises(StateStoreValidationError):
        target._failure_context(FailurePoint.PREPARE_AFTER_ARTIFACT_FSYNC, GENERATION, stage / "settings.json", "wrong-artifact")
    delivered: list[FailureContext] = []
    target.fault_injector = delivered.append
    with pytest.raises(StateStoreValidationError):
        target._hook(FailurePoint.PUBLISH_AFTER_STATE_FSYNC, GENERATION, tmp_path / "wrong-state")
    assert delivered == []
    reference = GenerationReference(GENERATION, "0" * 64)
    pointer = CurrentPointer(reference, canonical_json_sha256({"format": "aura.state-current.v1", "generation": GENERATION, "manifest_sha256": "0" * 64}))
    for inspection_type, valid in ((CurrentInspection, pointer), (GenerationInspection, None)):
        for issue in InspectionIssue:
            error = StateStoreIOError("io", operation=StateStoreOperation.READ_CURRENT, issue=issue)
            args = (InspectionStatus.IO_ERROR, None, issue, error)
            if issue in (InspectionIssue.IDENTITY_UNAVAILABLE, InspectionIssue.IO_FAILURE):
                assert inspection_type(*args).issue is issue
            else:
                with pytest.raises(StateStoreValidationError):
                    inspection_type(*args)
    orphan = generations / (".tmp-generation-" + GENERATION + "-" + "0" * 32)
    assert OrphanTemp(orphan, TempKind.GENERATION_DIRECTORY, GENERATION).path == orphan
    wrong_orphan = state / orphan.name
    assert OrphanTemp(wrong_orphan, TempKind.GENERATION_DIRECTORY, GENERATION).path == wrong_orphan
    with pytest.raises(StateStoreValidationError):
        target._orphan_temp(wrong_orphan, TempKind.GENERATION_DIRECTORY, GENERATION)


def test_orphan_discovery_returns_configured_directory_join_not_direntry_path(tmp_path: Path) -> None:
    target = store(tmp_path)
    target._ensure_layout(StateStoreOperation.FIND_ORPHAN_TEMPS)
    name = ".tmp-CURRENT-" + "0" * 32 + ".tmp"
    path = target.state_dir / name
    path.write_bytes(b"x")
    found = target.find_orphan_temps()
    assert found == (OrphanTemp(target.state_dir / name, TempKind.CURRENT_FILE, None),)


def test_pointer_partial_write_fsync_and_close_failures_clean_owned_temp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import core.state_store as state_module
    for failure in ("write", "fsync", "close"):
        root = tmp_path / failure
        root.mkdir()
        target = store(root)
        prepared = target.prepare_generation(generation=GENERATION, envelopes={"settings": envelope()})
        verifier = type("Yes", (), {"is_current_committed": lambda self, ref: True})()
        if failure == "write":
            monkeypatch.setattr(state_module.os, "write", lambda fd, data: 0)
        elif failure == "fsync":
            monkeypatch.setattr(state_module.os, "fsync", lambda fd: (_ for _ in ()).throw(OSError("fsync")))
        else:
            # Avoid read-generation handle closes; only the pointer creation is
            # relevant to this real close-failure gate.
            monkeypatch.setattr(target, "_read_generation", lambda reference, operation: None)
            real_close = target._close
            def close_then_report(fd: int, operation: StateStoreOperation, path: Path, *, advanced: bool = False) -> None:
                real_close(fd, operation, path, advanced=advanced)
                raise StateStoreIOError("close", operation=operation, path=path, issue=InspectionIssue.IO_FAILURE)
            monkeypatch.setattr(target, "_close", close_then_report)
        with pytest.raises(StateStoreIOError) as caught:
            target.publish_committed_generation(prepared.manifest.reference, verifier=verifier)
        assert caught.value.operation is StateStoreOperation.PUBLISH_COMMITTED_GENERATION
        assert not list(target.state_dir.glob(".tmp-CURRENT-*"))
        monkeypatch.undo()


@pytest.mark.parametrize("failure", ["write", "fsync", "close"])
def test_generation_stage_partial_write_fsync_and_close_failures_cleanup_owned_files(failure: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import core.state_store as state_module
    target = store(tmp_path)
    target._ensure_layout(StateStoreOperation.PREPARE_GENERATION)
    if failure == "write":
        monkeypatch.setattr(state_module.os, "write", lambda fd, data: 0)
    elif failure == "fsync":
        monkeypatch.setattr(state_module.os, "fsync", lambda fd: (_ for _ in ()).throw(OSError("fsync")))
    else:
        original_close = target._close
        def close_then_report(fd: int, operation: StateStoreOperation, path: Path, *, advanced: bool = False) -> None:
            original_close(fd, operation, path, advanced=advanced)
            raise StateStoreIOError("close", operation=operation, path=path, issue=InspectionIssue.IO_FAILURE)
        monkeypatch.setattr(target, "_close", close_then_report)
    with pytest.raises(StateStoreIOError) as caught:
        target.prepare_generation(generation=GENERATION, envelopes={"settings": envelope()})
    assert caught.value.operation is StateStoreOperation.PREPARE_GENERATION
    assert target.find_orphan_temps() == ()


@pytest.mark.parametrize("point", [
    FailurePoint.PREPARE_AFTER_STAGE_DIRECTORY,
    FailurePoint.PREPARE_AFTER_ARTIFACT_FSYNC,
    FailurePoint.PREPARE_AFTER_MANIFEST_FSYNC,
    FailurePoint.PREPARE_AFTER_STAGE_VALIDATION,
])
def test_pre_rename_failure_points_cleanup_owned_stage(point: FailurePoint, tmp_path: Path) -> None:
    marker = LookupError(point.value)
    def injector(context: FailureContext) -> None:
        if context.point is point:
            raise marker
    target = store(tmp_path)
    target.fault_injector = injector
    with pytest.raises(LookupError) as caught:
        target.prepare_generation(generation=GENERATION, envelopes={"settings": envelope()})
    assert caught.value is marker
    assert target.find_orphan_temps() == ()


def test_generation_stage_swap_and_unexpected_child_refuse_cleanup_with_note(tmp_path: Path) -> None:
    target = store(tmp_path)
    replacement = tmp_path / "replacement.json"
    replacement.write_bytes(b"replacement")
    def swap_child(context: FailureContext) -> None:
        if context.point is FailurePoint.PREPARE_AFTER_ARTIFACT_FSYNC:
            os.replace(replacement, context.path)
    target.fault_injector = swap_child
    with pytest.raises(StateStoreError) as swapped:
        target.prepare_generation(generation=GENERATION, envelopes={"settings": envelope()})
    assert any("owned staging cleanup failed" in note for note in getattr(swapped.value, "__notes__", ()))
    assert [item.kind for item in target.find_orphan_temps()] == [TempKind.GENERATION_DIRECTORY]

    second_root = tmp_path / "unexpected"
    second_root.mkdir()
    second = store(second_root)
    def add_child(context: FailureContext) -> None:
        if context.point is FailurePoint.PREPARE_AFTER_MANIFEST_FSYNC:
            (context.path.parent / "unexpected").write_bytes(b"x")
    second.fault_injector = add_child
    with pytest.raises(StateStoreError) as unexpected:
        second.prepare_generation(generation=GENERATION, envelopes={"settings": envelope()})
    assert any("owned staging cleanup failed" in note for note in getattr(unexpected.value, "__notes__", ()))
    assert [item.kind for item in second.find_orphan_temps()] == [TempKind.GENERATION_DIRECTORY]


@pytest.mark.parametrize("target_name", ["settings.json", "MANIFEST.json"])
def test_generation_write_rejects_byte_identical_post_close_replacement(target_name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = store(tmp_path)
    original_close = target._close
    swapped = False
    def close_then_replace(fd: int, operation: StateStoreOperation, path: Path, *, advanced: bool = False) -> None:
        nonlocal swapped
        original_close(fd, operation, path, advanced=advanced)
        if not swapped and path.name == target_name:
            replacement = tmp_path / ("replacement-" + target_name)
            replacement.write_bytes(path.read_bytes())
            os.replace(replacement, path)
            swapped = True
    monkeypatch.setattr(target, "_close", close_then_replace)
    with pytest.raises(StateCorruptionError) as caught:
        target.prepare_generation(generation=GENERATION, envelopes={"settings": envelope()})
    assert swapped is True
    assert caught.value.operation is StateStoreOperation.PREPARE_GENERATION
    assert caught.value.path is not None and caught.value.path.name == target_name
    assert caught.value.issue is InspectionIssue.IDENTITY_CHANGED
    assert caught.value.durable_state_may_have_advanced is False
    assert [item.kind for item in target.find_orphan_temps()] == [TempKind.GENERATION_DIRECTORY]


def test_pointer_write_rejects_byte_identical_post_close_replacement(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = store(tmp_path)
    prepared = target.prepare_generation(generation=GENERATION, envelopes={"settings": envelope()})
    original_close = target._close
    swapped_path: Path | None = None
    def close_then_replace(fd: int, operation: StateStoreOperation, path: Path, *, advanced: bool = False) -> None:
        nonlocal swapped_path
        original_close(fd, operation, path, advanced=advanced)
        if swapped_path is None and path.name.startswith(".tmp-CURRENT-"):
            replacement = tmp_path / "replacement-pointer"
            replacement.write_bytes(path.read_bytes())
            os.replace(replacement, path)
            swapped_path = path
    monkeypatch.setattr(target, "_close", close_then_replace)
    verifier = type("Yes", (), {"is_current_committed": lambda self, ref: True})()
    with pytest.raises(StateCorruptionError) as caught:
        target.publish_committed_generation(prepared.manifest.reference, verifier=verifier)
    assert swapped_path is not None
    assert caught.value.operation is StateStoreOperation.PUBLISH_COMMITTED_GENERATION
    assert caught.value.path == swapped_path
    assert caught.value.issue is InspectionIssue.IDENTITY_CHANGED
    assert caught.value.durable_state_may_have_advanced is False
    assert swapped_path.exists() and swapped_path.read_bytes().startswith(b'{"format"')


@pytest.mark.parametrize(("kind", "expected_error", "issue"), [
    ("reparse", StateCorruptionError, InspectionIssue.LINK_OR_REPARSE),
    ("hard_link", StateCorruptionError, InspectionIssue.HARD_LINK),
    ("zero_identity", StateStoreIOError, InspectionIssue.IDENTITY_UNAVAILABLE),
])
@pytest.mark.parametrize("leaf_kind", ["durable_manifest", "pointer_temp"])
def test_windows_metadata_oracle_rejects_durable_and_temp_leaves_on_every_host(kind: str, expected_error: type[StateStoreError], issue: InspectionIssue, leaf_kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import core.state_store as state_module
    target = store(tmp_path)
    target._ensure_layout(StateStoreOperation.PREPARE_GENERATION)
    if leaf_kind == "durable_manifest":
        durable_dir = target.generations_dir / GENERATION
        durable_dir.mkdir()
        leaf = durable_dir / "MANIFEST.json"
    else:
        leaf = target.state_dir / ".tmp-CURRENT-00000000000000000000000000000000.tmp"
    leaf.write_bytes(b"x")
    real_lstat = state_module.os.lstat
    attributes = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if kind == "reparse":
        fake = SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_dev=1, st_ino=1, st_nlink=1, st_file_attributes=attributes)
    elif kind == "hard_link":
        fake = SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_dev=1, st_ino=1, st_nlink=2, st_file_attributes=0)
    else:
        fake = SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_dev=1, st_ino=0, st_nlink=1, st_file_attributes=0)
    def leaf_metadata(path: object) -> object:
        return fake if os.fspath(path).endswith(leaf.name) else real_lstat(path)
    monkeypatch.setattr(state_module.os, "name", "nt")
    monkeypatch.setattr(state_module.os, "lstat", leaf_metadata)
    with pytest.raises(expected_error) as caught:
        target._meta(leaf, StateStoreOperation.READ_CURRENT, directory=False, single=True)
    assert caught.value.issue is issue


def test_real_symlink_current_is_rejected_or_skips_only_windows_privilege_error(tmp_path: Path) -> None:
    target = store(tmp_path)
    target._ensure_layout(StateStoreOperation.READ_CURRENT)
    source = target.state_dir / "symlink-source"
    source.write_bytes(b"not a pointer")
    try:
        os.symlink(source, target.current_path)
    except OSError as exc:
        if os.name == "nt" and getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows symlink privilege is unavailable")
        raise
    with pytest.raises(StateCorruptionError) as caught:
        target.read_current()
    assert caught.value.issue is InspectionIssue.LINK_OR_REPARSE


def test_pointer_partial_cleanup_refuses_swapped_file_and_adds_note(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = store(tmp_path)
    prepared = target.prepare_generation(generation=GENERATION, envelopes={"settings": envelope()})
    verifier = type("Yes", (), {"is_current_committed": lambda self, ref: True})()
    original_write = target._write_file
    marker = StateStoreIOError("partial pointer", operation=StateStoreOperation.PUBLISH_COMMITTED_GENERATION)
    replacement = tmp_path / "replacement"
    replacement.write_bytes(b"replacement")
    def create_then_swap(path: Path, data: bytes, operation: StateStoreOperation, on_created: object = None) -> tuple[int, int]:
        identity = original_write(path, b"x", operation, on_created)
        os.replace(replacement, path)
        raise marker
    monkeypatch.setattr(target, "_write_file", create_then_swap)
    with pytest.raises(StateStoreIOError) as caught:
        target.publish_committed_generation(prepared.manifest.reference, verifier=verifier)
    assert caught.value is marker
    notes = getattr(marker, "__notes__", ())
    assert any("owned pointer cleanup failed" in note for note in notes)
    leftovers = list(target.state_dir.glob(".tmp-CURRENT-*"))
    assert len(leftovers) == 1 and leftovers[0].read_bytes() == b"replacement"


def test_pointer_cleanup_failure_keeps_original_exception_and_note(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = store(tmp_path)
    prepared = target.prepare_generation(generation=GENERATION, envelopes={"settings": envelope()})
    marker = StateStoreIOError("write failed", operation=StateStoreOperation.PUBLISH_COMMITTED_GENERATION)
    original_write = target._write_file
    def create_then_fail(path: Path, data: bytes, operation: StateStoreOperation, on_created: object = None) -> tuple[int, int]:
        original_write(path, b"x", operation, on_created)
        raise marker
    monkeypatch.setattr(target, "_write_file", create_then_fail)
    monkeypatch.setattr(target, "_cleanup_pointer", lambda path, identity, operation: (_ for _ in ()).throw(RuntimeError("cleanup denied")))
    with pytest.raises(StateStoreIOError) as caught:
        target.publish_committed_generation(prepared.manifest.reference, verifier=type("Yes", (), {"is_current_committed": lambda self, ref: True})())
    assert caught.value is marker
    assert any("owned pointer cleanup failed: cleanup denied" in note for note in getattr(marker, "__notes__", ()))


@pytest.mark.parametrize("seam", [
    FailurePoint.PREPARE_AFTER_STAGE_VALIDATION.value,
    FailurePoint.PREPARE_AFTER_GENERATION_RENAME.value,
    FailurePoint.PUBLISH_BEFORE_POINTER_REPLACE.value,
    FailurePoint.PUBLISH_AFTER_POINTER_REPLACE.value,
])
def test_subprocess_crash_cuts_leave_deterministic_inspection(seam: str, tmp_path: Path) -> None:
    root = tmp_path / "crash-state"
    root.mkdir()
    script = textwrap.dedent("""
        import os, sys
        from pathlib import Path
        from core.contracts import PersistedEnvelope
        from core.schema_registry import SchemaRegistry
        from core.state_store import FailurePoint, StateStore
        root = Path(sys.argv[1]).resolve(); seam = sys.argv[2]
        registry = SchemaRegistry(); registry.register(schema='aura.settings', version=1, validator=lambda payload: None); registry.freeze()
        store = StateStore(state_dir=root/'state', generations_dir=root/'state'/'generations', current_path=root/'state'/'CURRENT', registry=registry,
            fault_injector=lambda context: os._exit(86) if context.point.value == seam else None)
        generation = 'g-0123456789abcdef0123456789abcdef'
        envelope = PersistedEnvelope.create(schema='aura.settings', schema_version=1, revision=0, generation=generation, updated_at_ns=0, payload={'provider':'local','temperature':-0.0})
        prepared = store.prepare_generation(generation=generation, envelopes={'settings': envelope})
        store.publish_committed_generation(prepared.manifest.reference, verifier=type('Yes', (), {'is_current_committed': lambda self, ref: True})())
    """)
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONPATH"] = str(Path.cwd())
    completed = subprocess.run([sys.executable, "-B", "-c", script, str(root), seam], cwd=Path.cwd(), env=environment,
        text=True, capture_output=True, timeout=20)
    assert completed.returncode == 86, completed.stderr
    target = store(root)
    expected = target._generation_manifest(GENERATION, {"settings": envelope()}).reference
    generation_inspection = target.inspect_generation(expected)
    if seam == FailurePoint.PREPARE_AFTER_STAGE_VALIDATION.value:
        assert generation_inspection.status is InspectionStatus.MISSING
        assert [item.kind for item in target.find_orphan_temps()] == [TempKind.GENERATION_DIRECTORY]
        assert target.inspect_current().status is InspectionStatus.MISSING
    else:
        assert generation_inspection.status is InspectionStatus.VALID
    if seam == FailurePoint.PUBLISH_AFTER_POINTER_REPLACE.value:
        assert target.inspect_current().pointer is not None
        assert target.inspect_current().pointer.reference == expected
    elif seam == FailurePoint.PUBLISH_BEFORE_POINTER_REPLACE.value:
        assert target.inspect_current().status is InspectionStatus.MISSING
        assert [item.kind for item in target.find_orphan_temps()] == [TempKind.CURRENT_FILE]
    elif seam == FailurePoint.PREPARE_AFTER_GENERATION_RENAME.value:
        assert target.inspect_current().status is InspectionStatus.MISSING


def test_threaded_publication_and_current_readers_observe_only_complete_pointers(tmp_path: Path) -> None:
    target = store(tmp_path)
    first = target.prepare_generation(generation=GENERATION, envelopes={"settings": envelope()}).manifest.reference
    generation_two = "g-fedcba98765432100123456789abcdef"
    two = PersistedEnvelope.create(schema="aura.settings", schema_version=1, revision=1, generation=generation_two,
        updated_at_ns=1, payload={"provider": "local"})
    second = target.prepare_generation(generation=generation_two, envelopes={"settings": two}).manifest.reference
    verifier = type("Yes", (), {"is_current_committed": lambda self, ref: True})()
    done = threading.Event()
    seen: list[GenerationReference] = []
    errors: list[BaseException] = []
    def publisher() -> None:
        try:
            for index in range(40):
                target.publish_committed_generation(first if index % 2 == 0 else second, verifier=verifier)
        except BaseException as exc:
            errors.append(exc)
        finally:
            done.set()
    def reader() -> None:
        try:
            while not done.is_set():
                current = target.read_current()
                if current is not None:
                    seen.append(current.reference)
                if len(seen) >= 200:
                    return
            current = target.read_current()
            if current is not None:
                seen.append(current.reference)
        except BaseException as exc:
            errors.append(exc)
    writer = threading.Thread(target=publisher)
    observer = threading.Thread(target=reader)
    writer.start(); observer.start(); writer.join(20); done.set(); observer.join(20)
    assert not writer.is_alive() and not observer.is_alive()
    assert not errors and seen and set(seen) <= {first, second}


def test_canonical_depth_node_raw_and_pointer_checksum_classification(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from core.contracts import canonical_json_bytes
    shallow: object = 0
    for _ in range(MAX_CANONICAL_DEPTH - 1):
        shallow = [shallow]
    assert parse_canonical_json_bytes(canonical_json_bytes(shallow))
    too_deep: object = shallow
    too_deep = [too_deep]
    with pytest.raises(CanonicalJSONError):
        canonical_json_bytes(too_deep)
    monkeypatch.setattr("core.contracts.MAX_CANONICAL_NODES", 3)
    with pytest.raises(CanonicalJSONError):
        canonical_json_bytes([0, 1, 2])
    monkeypatch.undo()
    target = store(tmp_path)
    prepared = target.prepare_generation(generation=GENERATION, envelopes={"settings": envelope()})
    pointer = CurrentPointer(prepared.manifest.reference, canonical_json_sha256({"format": "aura.state-current.v1", "generation": GENERATION, "manifest_sha256": prepared.manifest.reference.manifest_sha256}))
    bad_hash = dict(parse_canonical_json_bytes(pointer.to_bytes()))
    bad_hash["pointer_sha256"] = "0" * 64
    target.current_path.write_bytes(canonical_json_bytes(bad_hash))
    assert target.inspect_current().issue is InspectionIssue.CHECKSUM_MISMATCH
    target.current_path.write_bytes(canonical_json_bytes({"format": "aura.state-current.v1"}))
    assert target.inspect_current().issue is InspectionIssue.INVALID_FRAMING


def test_canonical_input_and_output_byte_limits_are_exact_and_one_over() -> None:
    prefix, suffix = b'{"x":"', b'"}'
    exact_input = prefix + (b"a" * (MAX_CANONICAL_JSON_BYTES - len(prefix) - len(suffix))) + suffix
    assert len(exact_input) == MAX_CANONICAL_JSON_BYTES
    assert parse_canonical_json_bytes(exact_input)
    with pytest.raises(CanonicalJSONError):
        parse_canonical_json_bytes(exact_input + b" ")
    value = {"x": "a" * (MAX_CANONICAL_JSON_BYTES - len(prefix) - len(suffix))}
    assert len(canonical_json_bytes(value)) == MAX_CANONICAL_JSON_BYTES
    with pytest.raises(CanonicalJSONError):
        canonical_json_bytes({"x": value["x"] + "a"})


@pytest.mark.parametrize("decoder_error", [ValueError, OverflowError, RecursionError])
def test_raw_json_decoder_value_overflow_and_recursion_errors_become_canonical_errors(decoder_error: type[Exception], monkeypatch: pytest.MonkeyPatch) -> None:
    import core.contracts as contracts_module
    def broken_loads(*args: object, **kwargs: object) -> object:
        raise decoder_error("decoder boundary")
    monkeypatch.setattr(contracts_module.json, "loads", broken_loads)
    with pytest.raises(CanonicalJSONError):
        parse_canonical_json_bytes(b"{}")


def test_post_advance_internal_failures_use_public_operation_and_advanced_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prepare_seen: list[FailureContext] = []
    target = store(tmp_path)
    target.fault_injector = prepare_seen.append
    original_flush = target._flush_dir
    def fail_generation_flush(path: Path, operation: StateStoreOperation) -> DurabilityLevel:
        if path == target.generations_dir and (target.generations_dir / GENERATION).is_dir():
            raise StateStoreIOError("nested flush", operation=StateStoreOperation.READ_CURRENT, path=path,
                issue=InspectionIssue.IO_FAILURE)
        return original_flush(path, operation)
    monkeypatch.setattr(target, "_flush_dir", fail_generation_flush)
    with pytest.raises(StateStoreIOError) as prepared_error:
        target.prepare_generation(generation=GENERATION, envelopes={"settings": envelope()})
    assert prepared_error.value.operation is StateStoreOperation.PREPARE_GENERATION
    assert prepared_error.value.durable_state_may_have_advanced is True
    assert FailurePoint.PREPARE_AFTER_GENERATION_RENAME in [item.point for item in prepare_seen]
    expected = target._generation_manifest(GENERATION, {"settings": envelope()}).reference
    assert target.inspect_generation(expected).status is InspectionStatus.VALID
    monkeypatch.undo()

    publish_seen: list[FailureContext] = []
    target.fault_injector = publish_seen.append
    prepared = target.prepare_generation(generation=GENERATION, envelopes={"settings": envelope()})
    original_flush = target._flush_dir
    def fail_state_flush(path: Path, operation: StateStoreOperation) -> DurabilityLevel:
        if path == target.state_dir and target.current_path.exists():
            raise StateStoreIOError("nested flush", operation=StateStoreOperation.READ_CURRENT, path=path,
                issue=InspectionIssue.IO_FAILURE)
        return original_flush(path, operation)
    monkeypatch.setattr(target, "_flush_dir", fail_state_flush)
    verifier = type("Yes", (), {"is_current_committed": lambda self, ref: True})()
    with pytest.raises(StateStoreIOError) as published_error:
        target.publish_committed_generation(prepared.manifest.reference, verifier=verifier)
    assert published_error.value.operation is StateStoreOperation.PUBLISH_COMMITTED_GENERATION
    assert published_error.value.durable_state_may_have_advanced is True
    assert FailurePoint.PUBLISH_AFTER_POINTER_REPLACE in [item.point for item in publish_seen]
    assert target.inspect_current().pointer is not None
