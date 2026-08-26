"""Canonical, side-effect-free framing used by durable checkpoint state."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
import re
from types import MappingProxyType
from typing import Final, Generic, Mapping, TypeAlias, TypeVar, cast

MAX_SIGNED_INT64: Final[int] = 9_223_372_036_854_775_807
MIN_SIGNED_INT64: Final[int] = -9_223_372_036_854_775_808
MAX_CANONICAL_JSON_BYTES: Final[int] = 16_777_216
MAX_CANONICAL_DEPTH: Final[int] = 64
MAX_CANONICAL_NODES: Final[int] = 1_000_000

CanonicalScalar: TypeAlias = None | bool | int | float | str
CanonicalValue: TypeAlias = CanonicalScalar | tuple["CanonicalValue", ...] | Mapping[str, "CanonicalValue"]
T = TypeVar("T")

_SCHEMA = re.compile(r"^[a-z][a-z0-9_-]{0,31}(?:\.[a-z][a-z0-9_-]{0,31}){1,3}$")
_GENERATION = re.compile(r"^g-[0-9a-f]{32}$")
_ARTIFACT = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FIELDS: Final[frozenset[str]] = frozenset(("schema", "schema_version", "revision", "generation", "updated_at_ns", "payload_sha256", "payload"))


class ContractError(ValueError):
    pass


class CanonicalJSONError(ContractError):
    pass


class EnvelopeValidationError(ContractError):
    pass


def _bad_text(value: str) -> bool:
    try:
        value.encode("utf-8", "strict")
    except UnicodeError:
        return True
    return False


def _freeze(value: object, *, depth: int = 1, counter: list[int] | None = None) -> CanonicalValue:
    if counter is None:
        counter = [0]
    if depth > MAX_CANONICAL_DEPTH:
        raise CanonicalJSONError("canonical value is too deeply nested")
    counter[0] += 1
    if counter[0] > MAX_CANONICAL_NODES:
        raise CanonicalJSONError("canonical value has too many nodes")
    if value is None or type(value) is bool:
        return value
    if type(value) is int:
        if not MIN_SIGNED_INT64 <= value <= MAX_SIGNED_INT64:
            raise CanonicalJSONError("integer is outside signed int64")
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise CanonicalJSONError("float must be finite")
        return 0.0 if value == 0.0 else value
    if type(value) is str:
        if _bad_text(value):
            raise CanonicalJSONError("string contains an unpaired surrogate")
        return value
    if type(value) in (list, tuple):
        sequence = cast(list[object] | tuple[object, ...], value)
        return tuple(_freeze(item, depth=depth + 1, counter=counter) for item in sequence)
    if type(value) in (dict, MappingProxyType):
        mapping = cast(Mapping[object, object], value)
        frozen: dict[str, CanonicalValue] = {}
        for key, item in mapping.items():
            if type(key) is not str:
                raise CanonicalJSONError("object keys must be exact strings")
            if _bad_text(key):
                raise CanonicalJSONError("object key contains an unpaired surrogate")
            counter[0] += 1
            if counter[0] > MAX_CANONICAL_NODES:
                raise CanonicalJSONError("canonical value has too many nodes")
            frozen[key] = _freeze(item, depth=depth + 1, counter=counter)
        return MappingProxyType(dict(sorted(frozen.items())))
    raise CanonicalJSONError("value has a non-canonical type")


def _mutable(value: CanonicalValue) -> object:
    if type(value) is tuple:
        return [_mutable(item) for item in value]
    if isinstance(value, Mapping):
        return {key: _mutable(item) for key, item in value.items()}
    return value


def canonical_json_bytes(value: object, /) -> bytes:
    frozen = _freeze(value)
    try:
        data = json.dumps(_mutable(frozen), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8", "strict")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise CanonicalJSONError("cannot encode canonical JSON") from exc
    if len(data) > MAX_CANONICAL_JSON_BYTES:
        raise CanonicalJSONError("canonical JSON exceeds byte limit")
    return data


def canonical_json_sha256(value: object, /) -> str:
    return sha256(canonical_json_bytes(value)).hexdigest()


def _no_duplicates(pairs: list[tuple[object, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if type(key) is not str or key in result:
            raise CanonicalJSONError("duplicate or non-string JSON object key")
        result[key] = value
    return result


def parse_canonical_json_bytes(data: bytes, /) -> CanonicalValue:
    if type(data) is not bytes or not data or len(data) > MAX_CANONICAL_JSON_BYTES:
        raise CanonicalJSONError("invalid canonical JSON byte input")
    try:
        text = data.decode("utf-8", "strict")
        parsed = json.loads(text, object_pairs_hook=_no_duplicates, parse_constant=lambda _: (_ for _ in ()).throw(CanonicalJSONError("non-finite JSON number")))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError, OverflowError, RecursionError, CanonicalJSONError) as exc:
        if isinstance(exc, CanonicalJSONError):
            raise
        raise CanonicalJSONError("invalid JSON") from exc
    frozen = _freeze(parsed)
    if canonical_json_bytes(frozen) != data:
        raise CanonicalJSONError("JSON bytes are not canonical")
    return frozen


def validate_schema(value: object) -> str:
    if type(value) is not str or len(value) > 128 or not _SCHEMA.fullmatch(value):
        raise EnvelopeValidationError("invalid schema identifier")
    return value


def validate_generation(value: object) -> str:
    if type(value) is not str or not _GENERATION.fullmatch(value):
        raise EnvelopeValidationError("invalid generation identifier")
    return value


def validate_artifact_name(value: object) -> str:
    if type(value) is not str or not _ARTIFACT.fullmatch(value):
        raise EnvelopeValidationError("invalid artifact name")
    return value


def validate_sha256(value: object) -> str:
    if type(value) is not str or not _SHA256.fullmatch(value):
        raise EnvelopeValidationError("invalid sha256")
    return value


def _bounded_int(value: object, name: str, minimum: int) -> int:
    if type(value) is not int or value < minimum or value > MAX_SIGNED_INT64:
        raise EnvelopeValidationError(f"invalid {name}")
    return value


@dataclass(frozen=True, slots=True)
class PersistedEnvelope(Generic[T]):
    schema: str
    schema_version: int
    revision: int
    generation: str
    updated_at_ns: int
    payload_sha256: str
    payload: T

    def __post_init__(self) -> None:
        validate_schema(self.schema)
        _bounded_int(self.schema_version, "schema_version", 1)
        _bounded_int(self.revision, "revision", 0)
        validate_generation(self.generation)
        _bounded_int(self.updated_at_ns, "updated_at_ns", 0)
        validate_sha256(self.payload_sha256)
        try:
            frozen = _freeze(self.payload)
            actual = canonical_json_sha256(frozen)
        except CanonicalJSONError as exc:
            raise EnvelopeValidationError("invalid envelope payload") from exc
        if actual != self.payload_sha256:
            raise EnvelopeValidationError("payload sha256 mismatch")
        object.__setattr__(self, "payload", frozen)

    @classmethod
    def create(cls, *, schema: str, schema_version: int, revision: int, generation: str, updated_at_ns: int, payload: object) -> "PersistedEnvelope[CanonicalValue]":
        try:
            frozen = _freeze(payload)
        except CanonicalJSONError as exc:
            raise EnvelopeValidationError("invalid envelope payload") from exc
        return PersistedEnvelope[CanonicalValue](schema, schema_version, revision, generation, updated_at_ns, canonical_json_sha256(frozen), frozen)

    @classmethod
    def from_mapping(cls, value: Mapping[str, object], /) -> "PersistedEnvelope[CanonicalValue]":
        if type(value) not in (dict, MappingProxyType) or set(value) != _FIELDS:
            raise EnvelopeValidationError("envelope must contain exactly seven fields")
        return PersistedEnvelope[CanonicalValue](
            cast(str, value["schema"]), cast(int, value["schema_version"]), cast(int, value["revision"]),
            cast(str, value["generation"]), cast(int, value["updated_at_ns"]), cast(str, value["payload_sha256"]), cast(CanonicalValue, value["payload"]))

    @classmethod
    def from_bytes(cls, data: bytes, /) -> "PersistedEnvelope[CanonicalValue]":
        parsed = parse_canonical_json_bytes(data)
        if not isinstance(parsed, Mapping):
            raise EnvelopeValidationError("envelope must be an object")
        return cls.from_mapping(parsed)

    def to_mapping(self) -> dict[str, object]:
        return {"schema": self.schema, "schema_version": self.schema_version, "revision": self.revision, "generation": self.generation, "updated_at_ns": self.updated_at_ns, "payload_sha256": self.payload_sha256, "payload": _mutable(cast(CanonicalValue, self.payload))}

    def to_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_mapping())

    def validate(self) -> None:
        self.__post_init__()
