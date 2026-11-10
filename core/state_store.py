"""Immutable checkpoint generations and verifier-gated CURRENT publication."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import errno
from hashlib import sha256
import os
from pathlib import Path
import re
import secrets
import stat
import time
from types import MappingProxyType
from typing import TYPE_CHECKING, Mapping, Protocol, cast

from core.contracts import (MAX_CANONICAL_JSON_BYTES, MAX_SIGNED_INT64, CanonicalJSONError, CanonicalValue,
    EnvelopeValidationError, PersistedEnvelope, canonical_json_bytes,
    canonical_json_sha256, parse_canonical_json_bytes, validate_artifact_name, validate_schema,
    validate_generation, validate_sha256)
from core.schema_registry import (SchemaRegistry, SchemaRegistryError,
    UnknownSchemaError, UnsupportedSchemaVersionError, SchemaValidationError)
from core.utils import _windows_extended_path

if TYPE_CHECKING:
    from core.runtime_paths import RuntimePaths

_MANIFEST = "MANIFEST.json"
_GEN_TEMP = re.compile(r"^\.tmp-generation-(g-[0-9a-f]{32})-([0-9a-f]{32})$")
_CUR_TEMP = re.compile(r"^\.tmp-CURRENT-([0-9a-f]{32})\.tmp$")

class DurabilityLevel(StrEnum):
    FILES_AND_DIRECTORY = "files_and_directory"
    DIRECTORY_ENTRY_UNCONFIRMED = "directory_entry_unconfirmed"
class InspectionStatus(StrEnum):
    MISSING = "missing"; VALID = "valid"; CORRUPT = "corrupt"; IO_ERROR = "io_error"
class InspectionIssue(StrEnum):
    WRONG_TYPE = "wrong_type"; LINK_OR_REPARSE = "link_or_reparse"; HARD_LINK = "hard_link"
    IDENTITY_UNAVAILABLE = "identity_unavailable"; IDENTITY_CHANGED = "identity_changed"; PATH_ESCAPE = "path_escape"
    NON_CANONICAL_JSON = "non_canonical_json"; INVALID_FRAMING = "invalid_framing"; CHECKSUM_MISMATCH = "checksum_mismatch"
    UNREGISTERED_SCHEMA = "unregistered_schema"; SCHEMA_VALIDATION_FAILED = "schema_validation_failed"
    UNEXPECTED_ENTRY = "unexpected_entry"; IO_FAILURE = "io_failure"
class TempKind(StrEnum):
    GENERATION_DIRECTORY = "generation_directory"; CURRENT_FILE = "current_file"
class StateStoreOperation(StrEnum):
    CONSTRUCT = "construct"; PREPARE_GENERATION = "prepare_generation"; READ_GENERATION = "read_generation"
    READ_CURRENT = "read_current"; FIND_ORPHAN_TEMPS = "find_orphan_temps"; PUBLISH_COMMITTED_GENERATION = "publish_committed_generation"
class FailurePoint(StrEnum):
    PREPARE_AFTER_STAGE_DIRECTORY = "prepare.after_stage_directory"
    PREPARE_AFTER_ARTIFACT_FSYNC = "prepare.after_artifact_fsync"
    PREPARE_AFTER_MANIFEST_FSYNC = "prepare.after_manifest_fsync"
    PREPARE_AFTER_STAGE_VALIDATION = "prepare.after_stage_validation"
    PREPARE_AFTER_GENERATION_RENAME = "prepare.after_generation_rename"
    PREPARE_AFTER_GENERATIONS_FSYNC = "prepare.after_generations_fsync"
    PUBLISH_AFTER_COMMIT_PROOF = "publish.after_commit_proof"
    PUBLISH_AFTER_POINTER_TEMP_FSYNC = "publish.after_pointer_temp_fsync"
    PUBLISH_BEFORE_POINTER_REPLACE = "publish.before_pointer_replace"
    PUBLISH_AFTER_POINTER_REPLACE = "publish.after_pointer_replace"
    PUBLISH_AFTER_STATE_FSYNC = "publish.after_state_fsync"

class StateStoreError(RuntimeError):
    def __init__(self, message: str, *, operation: StateStoreOperation, path: Path | None = None,
                 failure_point: FailurePoint | None = None, durable_state_may_have_advanced: bool = False,
                 issue: InspectionIssue | None = None) -> None:
        if type(message) is not str or not message or type(operation) is not StateStoreOperation or (path is not None and not isinstance(path, Path)) or (failure_point is not None and type(failure_point) is not FailurePoint) or type(durable_state_may_have_advanced) is not bool or (issue is not None and type(issue) is not InspectionIssue):
            raise TypeError("invalid StateStoreError arguments")
        super().__init__(message); self.operation = operation; self.path = None if path is None else Path(path)
        self.failure_point = failure_point; self.durable_state_may_have_advanced = durable_state_may_have_advanced; self.issue = issue
class StateStoreValidationError(StateStoreError): pass
class StateStoreIOError(StateStoreError): pass
class StateCorruptionError(StateStoreError): pass
class GenerationConflictError(StateStoreError): pass
class UncommittedGenerationError(StateStoreError): pass
class StateStorePreconditionError(StateStoreError): pass

@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    name: str; file: str; schema: str; schema_version: int; revision: int; updated_at_ns: int; payload_sha256: str; envelope_sha256: str; byte_length: int
    def __post_init__(self) -> None:
        if (type(self.name) is not str or type(self.file) is not str or type(self.schema) is not str or
                type(self.schema_version) is not int or type(self.revision) is not int or
                type(self.updated_at_ns) is not int or type(self.payload_sha256) is not str or
                type(self.envelope_sha256) is not str or type(self.byte_length) is not int):
            raise _validation("invalid artifact record types")
        try: validate_artifact_name(self.name); validate_schema(self.schema); validate_sha256(self.payload_sha256); validate_sha256(self.envelope_sha256)
        except EnvelopeValidationError as exc: raise _validation(str(exc)) from exc
        if self.file != self.name + ".json" or type(self.schema_version) is not int or not 1 <= self.schema_version <= MAX_SIGNED_INT64 or type(self.revision) is not int or not 0 <= self.revision <= MAX_SIGNED_INT64 or type(self.updated_at_ns) is not int or not 0 <= self.updated_at_ns <= MAX_SIGNED_INT64 or type(self.byte_length) is not int or not 1 <= self.byte_length <= MAX_CANONICAL_JSON_BYTES:
            raise _validation("invalid artifact record")

@dataclass(frozen=True, slots=True)
class GenerationReference:
    generation: str; manifest_sha256: str
    def __post_init__(self) -> None:
        try: validate_generation(self.generation); validate_sha256(self.manifest_sha256)
        except EnvelopeValidationError as exc: raise _validation(str(exc)) from exc

def _manifest_body(reference: GenerationReference, revision: int, artifacts: tuple[ArtifactRecord, ...]) -> dict[str, object]:
    return {"format":"aura.state-generation.v1", "generation":reference.generation, "revision":revision,
            "artifacts": {a.name:{"file":a.file,"schema":a.schema,"schema_version":a.schema_version,"revision":a.revision,"updated_at_ns":a.updated_at_ns,"payload_sha256":a.payload_sha256,"envelope_sha256":a.envelope_sha256,"byte_length":a.byte_length} for a in artifacts}}

@dataclass(frozen=True, slots=True)
class GenerationManifest:
    reference: GenerationReference; revision: int; artifacts: tuple[ArtifactRecord, ...]
    def __post_init__(self) -> None:
        if type(self.reference) is not GenerationReference or type(self.revision) is not int or not 0 <= self.revision <= MAX_SIGNED_INT64 or type(self.artifacts) is not tuple or not 1 <= len(self.artifacts) <= 256 or any(type(item) is not ArtifactRecord for item in self.artifacts):
            raise _validation("invalid generation manifest")
        if tuple(a.name for a in self.artifacts) != tuple(sorted(a.name for a in self.artifacts)) or len({a.name for a in self.artifacts}) != len(self.artifacts) or len({a.file for a in self.artifacts}) != len(self.artifacts) or sum(a.byte_length for a in self.artifacts)>256*1024*1024 or any(a.revision != self.revision for a in self.artifacts):
            raise _validation("invalid generation artifact order")
        if canonical_json_sha256(_manifest_body(self.reference, self.revision, self.artifacts)) != self.reference.manifest_sha256:
            raise _validation("manifest sha256 mismatch")
    def to_bytes(self) -> bytes:
        body = _manifest_body(self.reference, self.revision, self.artifacts); body["manifest_sha256"] = self.reference.manifest_sha256
        return canonical_json_bytes(body)

@dataclass(frozen=True, slots=True)
class GenerationSnapshot:
    manifest: GenerationManifest; envelopes: Mapping[str, PersistedEnvelope[CanonicalValue]]
    def __post_init__(self) -> None:
        if type(self.manifest) is not GenerationManifest or type(self.envelopes) not in (dict, MappingProxyType): raise _validation("invalid envelopes mapping")
        records = {record.name:record for record in self.manifest.artifacts}
        if set(self.envelopes) != set(records): raise _validation("generation envelope names mismatch")
        frozen: dict[str, PersistedEnvelope[CanonicalValue]] = {}
        for name in sorted(records):
            envelope = self.envelopes[name]; record = records[name]
            if type(name) is not str or type(envelope) is not PersistedEnvelope or envelope.generation != self.manifest.reference.generation or envelope.revision != self.manifest.revision or (envelope.schema, envelope.schema_version, envelope.updated_at_ns, envelope.payload_sha256) != (record.schema,record.schema_version,record.updated_at_ns,record.payload_sha256) or sha256(envelope.to_bytes()).hexdigest() != record.envelope_sha256 or len(envelope.to_bytes()) != record.byte_length:
                raise _validation("generation envelope does not match manifest")
            frozen[name] = envelope
        object.__setattr__(self, "envelopes", MappingProxyType(frozen))

@dataclass(frozen=True, slots=True)
class PreparedGeneration:
    manifest: GenerationManifest; created: bool; durability: DurabilityLevel
    def __post_init__(self) -> None:
        if type(self.manifest) is not GenerationManifest or type(self.created) is not bool or type(self.durability) is not DurabilityLevel: raise _validation("invalid prepare result")
@dataclass(frozen=True, slots=True)
class CurrentPointer:
    reference: GenerationReference; pointer_sha256: str
    def __post_init__(self) -> None:
        if type(self.reference) is not GenerationReference: raise _validation("invalid current pointer reference")
        try: validate_sha256(self.pointer_sha256)
        except EnvelopeValidationError as exc: raise _validation(str(exc)) from exc
        if self.pointer_sha256 != canonical_json_sha256({"format":"aura.state-current.v1","generation":self.reference.generation,"manifest_sha256":self.reference.manifest_sha256}): raise _validation("pointer sha256 mismatch")
    def to_bytes(self) -> bytes:
        return canonical_json_bytes({"format":"aura.state-current.v1","generation":self.reference.generation,"manifest_sha256":self.reference.manifest_sha256,"pointer_sha256":self.pointer_sha256})
@dataclass(frozen=True, slots=True)
class PublicationResult:
    pointer: CurrentPointer; changed: bool; durability: DurabilityLevel
    def __post_init__(self) -> None:
        if type(self.pointer) is not CurrentPointer or type(self.changed) is not bool or type(self.durability) is not DurabilityLevel: raise _validation("invalid publication result")
@dataclass(frozen=True, slots=True)
class CurrentInspection:
    status: InspectionStatus; pointer: CurrentPointer | None; issue: InspectionIssue | None; error: StateCorruptionError | StateStoreIOError | None
    def __post_init__(self) -> None:
        if type(self.status) is not InspectionStatus:
            raise _validation("invalid current inspection status")
        if self.status is InspectionStatus.MISSING and self.pointer is self.issue is self.error is None:
            return
        if self.status is InspectionStatus.VALID and type(self.pointer) is CurrentPointer and self.issue is self.error is None:
            return
        if self.status is InspectionStatus.CORRUPT and self.pointer is None and type(self.issue) is InspectionIssue and type(self.error) is StateCorruptionError and self.error.issue is self.issue:
            return
        if self.status is InspectionStatus.IO_ERROR and self.pointer is None and self.issue in (InspectionIssue.IDENTITY_UNAVAILABLE, InspectionIssue.IO_FAILURE) and type(self.error) is StateStoreIOError and self.error.issue is self.issue:
            return
        raise _validation("invalid current inspection")
@dataclass(frozen=True, slots=True)
class GenerationInspection:
    status: InspectionStatus; snapshot: GenerationSnapshot | None; issue: InspectionIssue | None; error: StateCorruptionError | StateStoreIOError | None
    def __post_init__(self) -> None:
        if type(self.status) is not InspectionStatus:
            raise _validation("invalid generation inspection status")
        if self.status is InspectionStatus.MISSING and self.snapshot is self.issue is self.error is None:
            return
        if self.status is InspectionStatus.VALID and type(self.snapshot) is GenerationSnapshot and self.issue is self.error is None:
            return
        if self.status is InspectionStatus.CORRUPT and self.snapshot is None and type(self.issue) is InspectionIssue and type(self.error) is StateCorruptionError and self.error.issue is self.issue:
            return
        if self.status is InspectionStatus.IO_ERROR and self.snapshot is None and self.issue in (InspectionIssue.IDENTITY_UNAVAILABLE, InspectionIssue.IO_FAILURE) and type(self.error) is StateStoreIOError and self.error.issue is self.issue:
            return
        raise _validation("invalid generation inspection")
@dataclass(frozen=True, slots=True)
class OrphanTemp:
    path: Path; kind: TempKind; generation: str | None
    def __post_init__(self) -> None:
        if not isinstance(self.path, Path) or not self.path.is_absolute() or type(self.kind) is not TempKind:
            raise _validation("invalid orphan temp")
        generation_match = _GEN_TEMP.fullmatch(self.path.name)
        current_match = _CUR_TEMP.fullmatch(self.path.name)
        if self.kind is TempKind.GENERATION_DIRECTORY:
            if type(self.generation) is not str or generation_match is None or generation_match.group(1) != self.generation:
                raise _validation("invalid generation orphan temp")
        elif self.generation is not None or current_match is None:
            raise _validation("invalid CURRENT orphan temp")
@dataclass(frozen=True, slots=True)
class FailureContext:
    point: FailurePoint; generation: str; path: Path; artifact: str | None = None
    def __post_init__(self) -> None:
        if type(self.point) is not FailurePoint or not isinstance(self.path, Path) or not self.path.is_absolute():
            raise _validation("invalid fault context")
        try:
            validate_generation(self.generation)
        except EnvelopeValidationError as exc:
            raise _validation("invalid fault generation") from exc
        if self.point is not FailurePoint.PREPARE_AFTER_ARTIFACT_FSYNC and self.artifact is not None:
            raise _validation("unexpected fault artifact")
        stage_match = _GEN_TEMP.fullmatch(self.path.name)
        parent_stage_match = _GEN_TEMP.fullmatch(self.path.parent.name)
        if self.point in (FailurePoint.PREPARE_AFTER_STAGE_DIRECTORY, FailurePoint.PREPARE_AFTER_STAGE_VALIDATION):
            if stage_match is None or stage_match.group(1) != self.generation:
                raise _validation("fault staging directory name mismatch")
        if self.point is FailurePoint.PREPARE_AFTER_ARTIFACT_FSYNC:
            artifact = self.artifact
            try:
                validate_artifact_name(artifact)
            except EnvelopeValidationError as exc:
                raise _validation("invalid fault artifact") from exc
            if (type(artifact) is not str or self.path.name != artifact + ".json" or
                    parent_stage_match is None or parent_stage_match.group(1) != self.generation):
                raise _validation("fault artifact path mismatch")
        elif self.point is FailurePoint.PREPARE_AFTER_MANIFEST_FSYNC:
            if self.path.name != _MANIFEST or parent_stage_match is None or parent_stage_match.group(1) != self.generation:
                raise _validation("fault manifest path mismatch")
        elif self.point is FailurePoint.PREPARE_AFTER_GENERATION_RENAME:
            if self.path.name != self.generation:
                raise _validation("fault generation path mismatch")
        elif self.point is FailurePoint.PREPARE_AFTER_GENERATIONS_FSYNC:
            if self.path.name != "generations":
                raise _validation("fault generations directory name mismatch")
        elif self.point in (FailurePoint.PUBLISH_AFTER_COMMIT_PROOF, FailurePoint.PUBLISH_BEFORE_POINTER_REPLACE, FailurePoint.PUBLISH_AFTER_POINTER_REPLACE):
            if self.path.name != "CURRENT":
                raise _validation("fault CURRENT path mismatch")
        elif self.point is FailurePoint.PUBLISH_AFTER_POINTER_TEMP_FSYNC:
            if _CUR_TEMP.fullmatch(self.path.name) is None:
                raise _validation("fault CURRENT temporary path mismatch")
class FailureInjector(Protocol):
    def __call__(self, context: FailureContext, /) -> None: ...
class CommittedReferenceVerifier(Protocol):
    def is_current_committed(self, reference: GenerationReference, /) -> bool: ...

def _validation(message: str) -> StateStoreValidationError:
    return StateStoreValidationError(message, operation=StateStoreOperation.CONSTRUCT)

class StateStore:
    def __init__(self, *, state_dir: Path, generations_dir: Path, current_path: Path, registry: SchemaRegistry, fault_injector: FailureInjector | None = None) -> None:
        if type(registry) is not SchemaRegistry or not registry.is_frozen or (fault_injector is not None and not callable(fault_injector)):
            raise StateStorePreconditionError("a frozen schema registry is required", operation=StateStoreOperation.CONSTRUCT)
        raw_paths=(os.fspath(state_dir),os.fspath(generations_dir),os.fspath(current_path))
        if any(any(part in (".","..") for part in re.split(r"[\\/]", raw)) for raw in raw_paths):
            raise StateStorePreconditionError("state paths may not contain lexical dot components",operation=StateStoreOperation.CONSTRUCT)
        self.state_dir, self.generations_dir, self.current_path = Path(state_dir), Path(generations_dir), Path(current_path)
        if not all(path.is_absolute() for path in (self.state_dir,self.generations_dir,self.current_path)) or self.generations_dir != self.state_dir / "generations" or self.current_path != self.state_dir / "CURRENT":
            raise StateStorePreconditionError("state paths must be exact normalized absolute paths", operation=StateStoreOperation.CONSTRUCT)
        self.registry, self.fault_injector = registry, fault_injector
    @staticmethod
    def _io_path(path: Path) -> str:
        return _windows_extended_path(os.fspath(path), force=True)
    @staticmethod
    def _display_path(path: str) -> Path:
        """Normalise a Win32 extended path only for lexical comparisons."""
        if os.name == "nt" and path.startswith("\\\\?\\UNC\\"):
            path = "\\\\" + path[8:]
        elif os.name == "nt" and path.startswith("\\\\?\\"):
            path = path[4:]
        return Path(path)
    @classmethod
    def from_runtime_paths(cls, paths: "RuntimePaths", *, registry: SchemaRegistry, fault_injector: FailureInjector | None = None) -> "StateStore":
        return cls(state_dir=paths.state_dir, generations_dir=paths.state_generations_dir, current_path=paths.state_current_path, registry=registry, fault_injector=fault_injector)

    def _error(self, kind, message: str, op: StateStoreOperation, path: Path, issue: InspectionIssue, *, advanced: bool=False, point: FailurePoint | None=None, cause: Exception | None=None):
        error = kind(message, operation=op, path=path, issue=issue, durable_state_may_have_advanced=advanced, failure_point=point)
        if cause is not None: raise error from cause
        raise error
    @staticmethod
    def _advanced_error(error: StateStoreError, operation: StateStoreOperation) -> StateStoreError:
        """Frame post-publication internal failures at the caller boundary."""
        return type(error)(str(error), operation=operation, path=error.path,
            failure_point=error.failure_point, durable_state_may_have_advanced=True, issue=error.issue)
    def _identity(self, meta, path: Path, op: StateStoreOperation) -> tuple[int,int]:
        if os.name == "nt" and not hasattr(meta, "st_file_attributes"): self._error(StateStoreIOError,"identity metadata unavailable",op,path,InspectionIssue.IDENTITY_UNAVAILABLE)
        if hasattr(meta,"st_file_attributes") and meta.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT: self._error(StateCorruptionError,"reparse point",op,path,InspectionIssue.LINK_OR_REPARSE)
        if stat.S_ISLNK(meta.st_mode): self._error(StateCorruptionError,"symbolic link",op,path,InspectionIssue.LINK_OR_REPARSE)
        if type(meta.st_dev) is not int or type(meta.st_ino) is not int or not meta.st_ino: self._error(StateStoreIOError,"identity unavailable",op,path,InspectionIssue.IDENTITY_UNAVAILABLE)
        return meta.st_dev, meta.st_ino
    def _meta(self, path: Path, op: StateStoreOperation, *, directory: bool | None=None, single: bool=False):
        try: meta = os.lstat(self._io_path(path))
        except OSError as exc: self._error(StateStoreIOError,"metadata inspection failed",op,path,InspectionIssue.IO_FAILURE,cause=exc)
        self._identity(meta,path,op)
        if directory is True and not stat.S_ISDIR(meta.st_mode) or directory is False and not stat.S_ISREG(meta.st_mode): self._error(StateCorruptionError,"wrong path type",op,path,InspectionIssue.WRONG_TYPE)
        if single and meta.st_nlink != 1: self._error(StateCorruptionError,"hard linked durable file",op,path,InspectionIssue.HARD_LINK)
        return meta
    def _validate_bound_orphan(self, orphan: OrphanTemp) -> None:
        expected_parent = self.generations_dir if orphan.kind is TempKind.GENERATION_DIRECTORY else self.state_dir
        if orphan.path.parent != expected_parent:
            raise StateStoreValidationError("orphan temp is outside configured directory", operation=StateStoreOperation.FIND_ORPHAN_TEMPS,
                path=orphan.path, issue=InspectionIssue.PATH_ESCAPE)

    def _orphan_temp(self, path: Path, kind: TempKind, generation: str | None) -> OrphanTemp:
        orphan = OrphanTemp(path, kind, generation)
        self._validate_bound_orphan(orphan)
        return orphan

    def _validate_bound_failure_context(self, context: FailureContext) -> None:
        point, generation, path = context.point, context.generation, context.path
        stage_match = _GEN_TEMP.fullmatch(path.name)
        parent_stage_match = _GEN_TEMP.fullmatch(path.parent.name)
        if point in (FailurePoint.PREPARE_AFTER_STAGE_DIRECTORY, FailurePoint.PREPARE_AFTER_STAGE_VALIDATION):
            valid = path.parent == self.generations_dir and stage_match is not None and stage_match.group(1) == generation
        elif point is FailurePoint.PREPARE_AFTER_ARTIFACT_FSYNC:
            valid = (path.parent.parent == self.generations_dir and parent_stage_match is not None and
                parent_stage_match.group(1) == generation and context.artifact is not None and
                path.name == context.artifact + ".json")
        elif point is FailurePoint.PREPARE_AFTER_MANIFEST_FSYNC:
            valid = (path.parent.parent == self.generations_dir and parent_stage_match is not None and
                parent_stage_match.group(1) == generation and path.name == _MANIFEST)
        elif point is FailurePoint.PREPARE_AFTER_GENERATION_RENAME:
            valid = path == self.generations_dir / generation
        elif point is FailurePoint.PREPARE_AFTER_GENERATIONS_FSYNC:
            valid = path == self.generations_dir
        elif point in (FailurePoint.PUBLISH_AFTER_COMMIT_PROOF, FailurePoint.PUBLISH_BEFORE_POINTER_REPLACE, FailurePoint.PUBLISH_AFTER_POINTER_REPLACE):
            valid = path == self.current_path
        elif point is FailurePoint.PUBLISH_AFTER_POINTER_TEMP_FSYNC:
            valid = path.parent == self.state_dir and _CUR_TEMP.fullmatch(path.name) is not None
        elif point is FailurePoint.PUBLISH_AFTER_STATE_FSYNC:
            valid = path == self.state_dir
        else:
            valid = False
        if not valid:
            raise StateStoreValidationError("failure context does not match configured state paths", operation=StateStoreOperation.CONSTRUCT,
                path=path, issue=InspectionIssue.PATH_ESCAPE, failure_point=point)

    def _failure_context(self, point: FailurePoint, generation: str, path: Path, artifact: str | None = None) -> FailureContext:
        context = FailureContext(point, generation, path, artifact)
        self._validate_bound_failure_context(context)
        return context

    def _hook(self, point: FailurePoint, generation: str, path: Path, artifact: str | None=None) -> None:
        context = self._failure_context(point, generation, path, artifact)
        if self.fault_injector is not None: self.fault_injector(context)
    def _flush_dir(self, path: Path, op: StateStoreOperation) -> DurabilityLevel:
        if os.name == "nt": return DurabilityLevel.DIRECTORY_ENTRY_UNCONFIRMED
        flags=os.O_RDONLY | getattr(os,"O_DIRECTORY",0)
        try: fd=os.open(self._io_path(path),flags)
        except OSError as exc: self._error(StateStoreIOError,"directory flush open failed",op,path,InspectionIssue.IO_FAILURE,cause=exc)
        try: os.fsync(fd)
        except OSError as exc:
            if exc.errno in (errno.EINVAL,errno.ENOTSUP,getattr(errno,"EOPNOTSUPP",errno.ENOTSUP)): return DurabilityLevel.DIRECTORY_ENTRY_UNCONFIRMED
            self._error(StateStoreIOError,"directory flush failed",op,path,InspectionIssue.IO_FAILURE,cause=exc)
        finally:
            try: os.close(fd)
            except OSError as exc: self._error(StateStoreIOError,"directory close failed",op,path,InspectionIssue.IO_FAILURE,cause=exc)
        return DurabilityLevel.FILES_AND_DIRECTORY
    def _ensure_layout(self, op: StateStoreOperation) -> None:
        parent=self.state_dir.parent
        try:
            os.lstat(self._io_path(parent))
        except FileNotFoundError as exc:
            self._error(StateStorePreconditionError,"data parent does not exist",op,parent,InspectionIssue.PATH_ESCAPE,cause=exc)
        except OSError as exc:
            self._error(StateStoreIOError,"data parent metadata failed",op,parent,InspectionIssue.IO_FAILURE,cause=exc)
        self._meta(parent,op,directory=True)
        try:
            if self._display_path(os.path.realpath(self._io_path(parent))) != parent:
                self._error(StateStorePreconditionError,"untrusted data parent",op,parent,InspectionIssue.PATH_ESCAPE)
        except OSError as exc:
            self._error(StateStoreIOError,"data parent realpath failed",op,parent,InspectionIssue.IO_FAILURE,cause=exc)
        for path in (self.state_dir,self.generations_dir):
            if os.path.lexists(self._io_path(path)):
                self._meta(path,op,directory=True)
            else:
                try: os.mkdir(self._io_path(path))
                except OSError as exc: self._error(StateStoreIOError,"cannot create state directory",op,path,InspectionIssue.IO_FAILURE,cause=exc)
                self._meta(path,op,directory=True)
                self._flush_dir(path.parent,op)
    def _close(self, fd: int, op: StateStoreOperation, path: Path, *, advanced: bool = False) -> None:
        try:
            os.close(fd)
        except OSError as exc:
            self._error(StateStoreIOError,"file close failed",op,path,InspectionIssue.IO_FAILURE,advanced=advanced,cause=exc)
    def _read_file(self, path: Path, op: StateStoreOperation, *, mutable_current: bool = False) -> bytes:
        """Read a checked file.

        Generation files are immutable and therefore require the pathname to be
        the same object before, during, and after the read.  CURRENT is a
        replace-only pointer: an atomic replacement between lstat and open is
        safe, so retry that narrow race and accept the complete object obtained
        from a checked handle.
        """
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        attempts = 32 if mutable_current else 1
        last_missing: FileNotFoundError | None = None
        last_retryable: StateStoreIOError | None = None
        for _ in range(attempts):
            try:
                before = self._meta(path, op, directory=False, single=True)
            except StateStoreIOError as exc:
                if mutable_current and isinstance(exc.__cause__, (FileNotFoundError, PermissionError)):
                    last_retryable = exc
                    # Mirror the writer's back-off: an immediate retry can land
                    # inside the same Windows replacement window every time.
                    time.sleep(0.001)
                    continue
                raise
            identity = self._identity(before, path, op)
            try:
                fd = os.open(self._io_path(path), flags)
            except FileNotFoundError as exc:
                if mutable_current:
                    last_missing = exc
                    time.sleep(0.001)
                    continue
                self._error(StateStoreIOError, "file open failed", op, path, InspectionIssue.IO_FAILURE, cause=exc)
            except OSError as exc:
                if mutable_current and isinstance(exc, PermissionError):
                    last_retryable = StateStoreIOError("CURRENT open raced replacement", operation=op, path=path,
                        issue=InspectionIssue.IO_FAILURE)
                    time.sleep(0.001)
                    continue
                self._error(StateStoreIOError, "file open failed", op, path, InspectionIssue.IO_FAILURE, cause=exc)
            try:
                opened = os.fstat(fd)
                opened_identity = self._identity(opened, path, op)
                if opened_identity != identity:
                    if mutable_current:
                        continue
                    self._error(StateCorruptionError, "file identity changed", op, path, InspectionIssue.IDENTITY_CHANGED)
                data = bytearray()
                while len(data) <= MAX_CANONICAL_JSON_BYTES:
                    part = os.read(fd, min(65536, MAX_CANONICAL_JSON_BYTES + 1 - len(data)))
                    if not part:
                        break
                    data.extend(part)
                if len(data) > MAX_CANONICAL_JSON_BYTES:
                    self._error(StateCorruptionError, "file is oversized", op, path, InspectionIssue.INVALID_FRAMING)
            except OSError as exc:
                self._error(StateStoreIOError, "file read failed", op, path, InspectionIssue.IO_FAILURE, cause=exc)
            finally:
                self._close(fd, op, path)
            if mutable_current:
                return bytes(data)
            after = self._meta(path, op, directory=False, single=True)
            if self._identity(after, path, op) != identity:
                self._error(StateCorruptionError, "file identity changed", op, path, InspectionIssue.IDENTITY_CHANGED)
            return bytes(data)
        if last_missing is not None:
            self._error(StateStoreIOError, "CURRENT changed while opening", op, path, InspectionIssue.IO_FAILURE, cause=last_missing)
        if last_retryable is not None:
            raise last_retryable
        self._error(StateCorruptionError, "CURRENT changed while opening", op, path, InspectionIssue.IDENTITY_CHANGED)
    def _write_file(self,path:Path,data:bytes,op:StateStoreOperation, on_created=None) -> tuple[int,int]:
        flags=os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,"O_BINARY",0)|getattr(os,"O_NOFOLLOW",0)
        try: fd=os.open(self._io_path(path),flags,0o600)
        except OSError as exc: self._error(StateStoreIOError,"exclusive file creation failed",op,path,InspectionIssue.IO_FAILURE,cause=exc)
        try:
            created=self._identity(os.fstat(fd),path,op)
            if on_created is not None:
                on_created(created)
            offset=0
            while offset<len(data):
                progress=os.write(fd,data[offset:])
                if progress <= 0:
                    self._error(StateStoreIOError,"file write made no progress",op,path,InspectionIssue.IO_FAILURE)
                offset+=progress
            os.fsync(fd)
        except OSError as exc: self._error(StateStoreIOError,"file write or fsync failed",op,path,InspectionIssue.IO_FAILURE,cause=exc)
        finally: self._close(fd,op,path)
        final_identity = self._identity(self._meta(path,op,directory=False,single=True), path, op)
        if final_identity != created:
            self._error(StateCorruptionError, "file identity changed after close", op, path, InspectionIssue.IDENTITY_CHANGED)
        return created
    def _parse_manifest(self, data: bytes, op: StateStoreOperation, path: Path) -> GenerationManifest:
        try: raw=parse_canonical_json_bytes(data)
        except CanonicalJSONError as exc: self._error(StateCorruptionError,"non-canonical manifest JSON",op,path,InspectionIssue.NON_CANONICAL_JSON,cause=exc)
        if not isinstance(raw,Mapping) or set(raw)!={"format","generation","revision","artifacts","manifest_sha256"} or raw["format"]!="aura.state-generation.v1" or not isinstance(raw["artifacts"],Mapping): self._error(StateCorruptionError,"invalid manifest framing",op,path,InspectionIssue.INVALID_FRAMING)
        try:
            reference=GenerationReference(cast(str,raw["generation"]),cast(str,raw["manifest_sha256"])); revision=cast(int,raw["revision"])
            records=[]
            for name, value in raw["artifacts"].items():
                if type(name) is not str or not isinstance(value,Mapping) or set(value)!={"file","schema","schema_version","revision","updated_at_ns","payload_sha256","envelope_sha256","byte_length"}: raise ValueError("invalid artifact framing")
                records.append(ArtifactRecord(name,cast(str,value["file"]),cast(str,value["schema"]),cast(int,value["schema_version"]),cast(int,value["revision"]),cast(int,value["updated_at_ns"]),cast(str,value["payload_sha256"]),cast(str,value["envelope_sha256"]),cast(int,value["byte_length"])))
            body={"format":"aura.state-generation.v1","generation":reference.generation,"revision":revision,"artifacts":raw["artifacts"]}
            if canonical_json_sha256(body) != reference.manifest_sha256:
                self._error(StateCorruptionError,"manifest self-hash mismatch",op,path,InspectionIssue.CHECKSUM_MISMATCH)
            return GenerationManifest(reference,revision,tuple(records))
        except StateCorruptionError:
            # The self-hash is a precise corruption diagnosis, never framing.
            raise
        except (ValueError,TypeError,StateStoreError) as exc: self._error(StateCorruptionError,"invalid manifest framing",op,path,InspectionIssue.INVALID_FRAMING,cause=exc)
    def _read_generation(self, reference: GenerationReference, op: StateStoreOperation, *, directory: Path | None = None) -> GenerationSnapshot:
        final=self.generations_dir/reference.generation if directory is None else directory
        self._meta(final,op,directory=True)
        manifest_path=final/_MANIFEST
        manifest=self._parse_manifest(self._read_file(manifest_path,op),op,manifest_path)
        if manifest.reference != reference: self._error(StateCorruptionError,"generation reference mismatch",op,manifest_path,InspectionIssue.CHECKSUM_MISMATCH)
        try: names=sorted(entry.name for entry in os.scandir(self._io_path(final)))
        except OSError as exc: self._error(StateStoreIOError,"generation directory scan failed",op,final,InspectionIssue.IO_FAILURE,cause=exc)
        expected=sorted([_MANIFEST]+[record.file for record in manifest.artifacts])
        if names != expected: self._error(StateCorruptionError,"unexpected generation entry",op,final,InspectionIssue.UNEXPECTED_ENTRY)
        envelopes={}
        for record in manifest.artifacts:
            file=final/record.file
            data=self._read_file(file,op)
            if len(data)!=record.byte_length or sha256(data).hexdigest()!=record.envelope_sha256: self._error(StateCorruptionError,"artifact checksum mismatch",op,file,InspectionIssue.CHECKSUM_MISMATCH)
            try: envelope=PersistedEnvelope.from_bytes(data)
            except CanonicalJSONError as exc: self._error(StateCorruptionError,"non-canonical artifact JSON",op,file,InspectionIssue.NON_CANONICAL_JSON,cause=exc)
            except EnvelopeValidationError as exc: self._error(StateCorruptionError,"invalid artifact framing",op,file,InspectionIssue.INVALID_FRAMING,cause=exc)
            try: self.registry.validate_envelope(cast(PersistedEnvelope[object],envelope))
            except (UnknownSchemaError,UnsupportedSchemaVersionError) as exc: self._error(StateCorruptionError,"unregistered schema",op,file,InspectionIssue.UNREGISTERED_SCHEMA,cause=exc)
            except (SchemaRegistryError,EnvelopeValidationError) as exc: self._error(StateCorruptionError,"schema validation failed",op,file,InspectionIssue.SCHEMA_VALIDATION_FAILED,cause=exc)
            envelopes[record.name]=envelope
        try: return GenerationSnapshot(manifest,envelopes)
        except StateStoreValidationError as exc: self._error(StateCorruptionError,"generation snapshot invalid",op,final,InspectionIssue.INVALID_FRAMING,cause=exc)
    def _generation_plan(self, generation: str, envelopes: Mapping[str, PersistedEnvelope[object]]) -> tuple[GenerationManifest, tuple[tuple[str, PersistedEnvelope[object], bytes], ...]]:
        """Detach, validate, and encode every envelope exactly once."""
        if type(envelopes) not in (dict,MappingProxyType) or not 1<=len(envelopes)<=256: raise StateStoreValidationError("invalid envelope mapping",operation=StateStoreOperation.PREPARE_GENERATION)
        try: validate_generation(generation)
        except EnvelopeValidationError as exc: raise StateStoreValidationError("invalid generation",operation=StateStoreOperation.PREPARE_GENERATION) from exc
        copied=dict(envelopes); records=[]; plan=[]; revision=None
        aggregate=0
        for name in sorted(copied):
            envelope=copied[name]
            try: validate_artifact_name(name)
            except EnvelopeValidationError as exc: raise StateStoreValidationError("invalid artifact name",operation=StateStoreOperation.PREPARE_GENERATION) from exc
            if type(envelope) is not PersistedEnvelope or envelope.generation != generation: raise StateStoreValidationError("invalid envelope generation",operation=StateStoreOperation.PREPARE_GENERATION)
            if revision is None: revision=envelope.revision
            if envelope.revision != revision: raise StateStoreValidationError("mixed envelope revisions",operation=StateStoreOperation.PREPARE_GENERATION)
            try: self.registry.validate_envelope(envelope)
            except SchemaRegistryError as exc: raise StateStoreValidationError("schema validation failed",operation=StateStoreOperation.PREPARE_GENERATION) from exc
            data=envelope.to_bytes(); aggregate+=len(data)
            if aggregate>256*1024*1024: raise StateStoreValidationError("generation exceeds aggregate byte limit",operation=StateStoreOperation.PREPARE_GENERATION)
            records.append(ArtifactRecord(name,name+".json",envelope.schema,envelope.schema_version,envelope.revision,envelope.updated_at_ns,envelope.payload_sha256,sha256(data).hexdigest(),len(data)))
            plan.append((name, envelope, data))
        body={"format":"aura.state-generation.v1","generation":generation,"revision":revision,"artifacts":{record.name:{"file":record.file,"schema":record.schema,"schema_version":record.schema_version,"revision":record.revision,"updated_at_ns":record.updated_at_ns,"payload_sha256":record.payload_sha256,"envelope_sha256":record.envelope_sha256,"byte_length":record.byte_length} for record in records}}
        manifest = GenerationManifest(GenerationReference(generation,canonical_json_sha256(body)),cast(int,revision),tuple(records))
        return manifest, tuple(plan)
    def _generation_manifest(self,generation:str,envelopes:Mapping[str,PersistedEnvelope[object]]) -> GenerationManifest:
        return self._generation_plan(generation, envelopes)[0]
    def _cleanup_stage(self, stage: Path, stage_identity: tuple[int,int], files: list[tuple[Path,tuple[int,int]]], op: StateStoreOperation) -> None:
        try:
            if self._identity(self._meta(stage,op,directory=True),stage,op) != stage_identity:
                raise RuntimeError("staging directory identity changed")
            for file, identity in reversed(files):
                if self._identity(self._meta(file,op,directory=False,single=True),file,op) != identity:
                    raise RuntimeError("staging file identity changed")
                os.unlink(self._io_path(file))
            os.rmdir(self._io_path(stage))
        except Exception as exc:
            raise RuntimeError("owned staging cleanup was refused") from exc
    def prepare_generation(self, *, generation: str, envelopes: Mapping[str,PersistedEnvelope[object]]) -> PreparedGeneration:
        op=StateStoreOperation.PREPARE_GENERATION
        if type(envelopes) not in (dict,MappingProxyType):
            raise StateStoreValidationError("invalid envelope mapping",operation=op)
        manifest, plan = self._generation_plan(generation,envelopes)
        self._ensure_layout(op); final=self.generations_dir/generation
        if os.path.lexists(self._io_path(final)):
            try: snapshot=self._read_generation(manifest.reference,op)
            except StateStoreError as exc: raise GenerationConflictError("existing generation conflicts",operation=op,path=final,issue=exc.issue) from exc
            if snapshot.manifest != manifest: raise GenerationConflictError("existing generation conflicts",operation=op,path=final)
            return PreparedGeneration(manifest,False,self._flush_dir(self.generations_dir,op))
        stage=None; stage_identity=None; files: list[tuple[Path,tuple[int,int]]]=[]; advanced=False
        try:
            for _ in range(128):
                candidate=self.generations_dir/(".tmp-generation-"+generation+"-"+secrets.token_hex(16))
                try:
                    os.mkdir(self._io_path(candidate)); stage=candidate; stage_identity=self._identity(self._meta(stage,op,directory=True),stage,op); break
                except FileExistsError: continue
                except OSError as exc: self._error(StateStoreIOError,"cannot create staging directory",op,candidate,InspectionIssue.IO_FAILURE,cause=exc)
            if stage is None: raise StateStoreIOError("staging token collisions",operation=op,path=self.generations_dir)
            self._hook(FailurePoint.PREPARE_AFTER_STAGE_DIRECTORY,generation,stage)
            for name, _envelope, data in plan:
                path=stage/(name+".json"); self._write_file(path,data,op,lambda identity, p=path: files.append((p,identity))); self._hook(FailurePoint.PREPARE_AFTER_ARTIFACT_FSYNC,generation,path,name)
            mpath=stage/_MANIFEST; self._write_file(mpath,manifest.to_bytes(),op,lambda identity: files.append((mpath,identity))); self._hook(FailurePoint.PREPARE_AFTER_MANIFEST_FSYNC,generation,mpath)
            self._flush_dir(stage,op); self._read_generation_from_dir(stage,manifest.reference,op); self._hook(FailurePoint.PREPARE_AFTER_STAGE_VALIDATION,generation,stage)
            try: os.rename(self._io_path(stage),self._io_path(final))
            except OSError as exc: self._error(StateStoreIOError,"generation rename failed",op,final,InspectionIssue.IO_FAILURE,cause=exc)
            advanced=True; self._hook(FailurePoint.PREPARE_AFTER_GENERATION_RENAME,generation,final)
            try: durability=self._flush_dir(self.generations_dir,op)
            except StateStoreError as exc: raise self._advanced_error(exc, op) from exc
            self._hook(FailurePoint.PREPARE_AFTER_GENERATIONS_FSYNC,generation,self.generations_dir)
            try: self._read_generation(manifest.reference,op)
            except StateStoreError as exc: raise self._advanced_error(exc, op) from exc
            return PreparedGeneration(manifest,True,durability)
        except BaseException as exc:
            if not advanced and stage is not None and stage_identity is not None:
                try:
                    self._cleanup_stage(stage,stage_identity,files,op)
                except Exception as cleanup_error:
                    exc.add_note(f"owned staging cleanup failed: {cleanup_error}")
            raise
    def _read_generation_from_dir(self, directory:Path, reference:GenerationReference, op:StateStoreOperation) -> GenerationSnapshot:
        return self._read_generation(reference,op,directory=directory)
    def read_generation(self, reference: GenerationReference, /) -> GenerationSnapshot:
        if type(reference) is not GenerationReference: raise StateStoreValidationError("invalid generation reference",operation=StateStoreOperation.READ_GENERATION)
        return self._read_generation(reference,StateStoreOperation.READ_GENERATION)
    def inspect_generation(self, reference: GenerationReference, /) -> GenerationInspection:
        if type(reference) is not GenerationReference:
            raise StateStoreValidationError("invalid generation reference",operation=StateStoreOperation.READ_GENERATION)
        try:
            os.lstat(self._io_path(self.generations_dir / reference.generation))
        except FileNotFoundError:
            return GenerationInspection(InspectionStatus.MISSING,None,None,None)
        except OSError as exc:
            error=StateStoreIOError("generation metadata failed",operation=StateStoreOperation.READ_GENERATION,path=self.generations_dir / reference.generation,issue=InspectionIssue.IO_FAILURE)
            return GenerationInspection(InspectionStatus.IO_ERROR,None,error.issue,error)
        try: return GenerationInspection(InspectionStatus.VALID,self.read_generation(reference),None,None)
        except StateStoreIOError as exc:
            if isinstance(exc.__cause__,FileNotFoundError):
                error=StateCorruptionError("generation entry is missing",operation=StateStoreOperation.READ_GENERATION,path=exc.path,issue=InspectionIssue.INVALID_FRAMING)
                return GenerationInspection(InspectionStatus.CORRUPT,None,error.issue,error)
            return GenerationInspection(InspectionStatus.IO_ERROR,None,exc.issue,exc)
        except StateCorruptionError as exc: return GenerationInspection(InspectionStatus.CORRUPT,None,exc.issue,exc)
    def _pointer_from_bytes(self,data:bytes,op:StateStoreOperation,path:Path)->CurrentPointer:
        try: raw=parse_canonical_json_bytes(data)
        except CanonicalJSONError as exc: self._error(StateCorruptionError,"non-canonical CURRENT",op,path,InspectionIssue.NON_CANONICAL_JSON,cause=exc)
        try:
            if not isinstance(raw,Mapping) or set(raw)!={"format","generation","manifest_sha256","pointer_sha256"} or raw["format"]!="aura.state-current.v1": raise ValueError()
            reference=GenerationReference(cast(str,raw["generation"]),cast(str,raw["manifest_sha256"]))
            pointer_sha=cast(str,raw["pointer_sha256"])
            if pointer_sha != canonical_json_sha256({"format":"aura.state-current.v1","generation":reference.generation,"manifest_sha256":reference.manifest_sha256}):
                self._error(StateCorruptionError,"CURRENT self-hash mismatch",op,path,InspectionIssue.CHECKSUM_MISMATCH)
            return CurrentPointer(reference,pointer_sha)
        except StateCorruptionError:
            # Do not erase a valid CHECKSUM_MISMATCH diagnosis.
            raise
        except (ValueError,TypeError,StateStoreError) as exc: self._error(StateCorruptionError,"invalid CURRENT framing",op,path,InspectionIssue.INVALID_FRAMING,cause=exc)
    def read_current(self)->CurrentPointer|None:
        op=StateStoreOperation.READ_CURRENT
        # CURRENT is deliberately mutable. Once a checked regular file is open,
        # a concurrent atomic replacement may yield the complete old pointer.
        try: return self._pointer_from_bytes(self._read_file(self.current_path,op,mutable_current=True),op,self.current_path)
        except StateStoreIOError as exc:
            if isinstance(exc.__cause__,FileNotFoundError): return None
            raise
    def inspect_current(self)->CurrentInspection:
        try:
            pointer=self.read_current()
            return CurrentInspection(InspectionStatus.MISSING if pointer is None else InspectionStatus.VALID,pointer,None,None)
        except StateStoreIOError as exc: return CurrentInspection(InspectionStatus.IO_ERROR,None,exc.issue,exc)
        except StateCorruptionError as exc: return CurrentInspection(InspectionStatus.CORRUPT,None,exc.issue,exc)
    def find_orphan_temps(self)->tuple[OrphanTemp,...]:
        op=StateStoreOperation.FIND_ORPHAN_TEMPS; found=[]
        for directory,kind,pattern in ((self.generations_dir,TempKind.GENERATION_DIRECTORY,_GEN_TEMP),(self.state_dir,TempKind.CURRENT_FILE,_CUR_TEMP)):
            try: entries=list(os.scandir(self._io_path(directory)))
            except FileNotFoundError: continue
            except OSError as exc: self._error(StateStoreIOError,"temporary directory scan failed",op,directory,InspectionIssue.IO_FAILURE,cause=exc)
            for entry in entries:
                match=pattern.fullmatch(entry.name)
                if match is None: continue
                # DirEntry.path can retain a Win32 extended prefix.  Public
                # inspection DTOs always expose the configured lexical path.
                path=directory / entry.name
                self._meta(path,op,directory=(kind is TempKind.GENERATION_DIRECTORY),single=(kind is TempKind.CURRENT_FILE))
                found.append(self._orphan_temp(path,kind,match.group(1) if kind is TempKind.GENERATION_DIRECTORY else None))
        return tuple(sorted(found,key=lambda item:(item.kind.value,item.path.name)))
    def _cleanup_pointer(self,path:Path,identity:tuple[int,int],op:StateStoreOperation)->None:
        if self._identity(self._meta(path,op,directory=False,single=True),path,op) != identity:
            raise RuntimeError("pointer temporary identity changed")
        os.unlink(self._io_path(path))
    def publish_committed_generation(self, reference: GenerationReference, /, *, verifier: CommittedReferenceVerifier) -> PublicationResult:
        op=StateStoreOperation.PUBLISH_COMMITTED_GENERATION
        if type(reference) is not GenerationReference or verifier is None or not callable(getattr(verifier,"is_current_committed",None)):
            raise StateStoreValidationError("invalid publication arguments",operation=op)
        self._read_generation(reference,op)
        pointer=CurrentPointer(reference,canonical_json_sha256({"format":"aura.state-current.v1","generation":reference.generation,"manifest_sha256":reference.manifest_sha256}))
        # Verification is the authoritative publication gate.  It intentionally
        # runs exactly once for a valid invocation, including an idempotent one.
        # Exceptions are a verifier contract and must keep their identity.
        result=verifier.is_current_committed(reference)
        if type(result) is not bool or result is not True:
            raise UncommittedGenerationError("generation is not the current committed head",operation=op,path=self.current_path)
        try:
            existing=self.read_current()
            if existing == pointer: return PublicationResult(pointer,False,self._flush_dir(self.state_dir,op))
        except StateCorruptionError as exc:
            # Only a strictly-read regular CURRENT with malformed/checksum framing
            # may be replaced. Link/type/identity failures are never repaired.
            if exc.issue not in (InspectionIssue.NON_CANONICAL_JSON, InspectionIssue.INVALID_FRAMING, InspectionIssue.CHECKSUM_MISMATCH):
                raise
        self._hook(FailurePoint.PUBLISH_AFTER_COMMIT_PROOF,reference.generation,self.current_path)
        temp: tuple[Path,tuple[int,int]] | None = None; advanced=False
        try:
            for _ in range(128):
                candidate=self.state_dir/(".tmp-CURRENT-"+secrets.token_hex(16)+".tmp")
                temp = None
                try:
                    def record_creation(identity: tuple[int, int], *, _candidate: Path = candidate) -> None:
                        nonlocal temp
                        temp = (_candidate, identity)
                    self._write_file(candidate,pointer.to_bytes(),op,record_creation)
                    if temp is None:
                        raise RuntimeError("pointer creation identity was not recorded")
                    break
                except StateStoreIOError as exc:
                    if isinstance(exc.__cause__,FileExistsError): continue
                    raise
            if temp is None: raise StateStoreIOError("pointer token collisions",operation=op,path=self.state_dir)
            self._hook(FailurePoint.PUBLISH_AFTER_POINTER_TEMP_FSYNC,reference.generation,temp[0])
            self._hook(FailurePoint.PUBLISH_BEFORE_POINTER_REPLACE,reference.generation,self.current_path)
            if self._identity(self._meta(temp[0],op,directory=False,single=True),temp[0],op) != temp[1]:
                self._error(StateCorruptionError,"pointer temporary identity changed",op,temp[0],InspectionIssue.IDENTITY_CHANGED)
            replace_error: OSError | None = None
            for _ in range(32):
                try:
                    os.replace(self._io_path(temp[0]),self._io_path(self.current_path))
                    replace_error = None
                    break
                except PermissionError as exc:
                    # Windows may briefly deny replacement while a reader is
                    # closing an already-checked CURRENT handle.
                    replace_error = exc
                    time.sleep(0.001)
                except OSError as exc:
                    self._error(StateStoreIOError,"CURRENT replacement failed",op,self.current_path,InspectionIssue.IO_FAILURE,cause=exc)
            if replace_error is not None:
                self._error(StateStoreIOError,"CURRENT replacement failed",op,self.current_path,InspectionIssue.IO_FAILURE,cause=replace_error)
            advanced=True
            self._hook(FailurePoint.PUBLISH_AFTER_POINTER_REPLACE,reference.generation,self.current_path)
            try: durability=self._flush_dir(self.state_dir,op)
            except StateStoreError as exc: raise self._advanced_error(exc, op) from exc
            self._hook(FailurePoint.PUBLISH_AFTER_STATE_FSYNC,reference.generation,self.state_dir)
            try: actual=self.read_current()
            except StateStoreError as exc: raise self._advanced_error(exc, op) from exc
            if actual != pointer: self._error(StateCorruptionError,"published CURRENT did not verify",op,self.current_path,InspectionIssue.CHECKSUM_MISMATCH,advanced=True)
            return PublicationResult(pointer,True,durability)
        except BaseException as exc:
            if not advanced and temp is not None:
                try: self._cleanup_pointer(temp[0],temp[1],op)
                except Exception as cleanup_error: exc.add_note(f"owned pointer cleanup failed: {cleanup_error}")
            raise
