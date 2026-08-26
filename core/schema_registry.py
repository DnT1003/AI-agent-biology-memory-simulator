"""Pure, frozen in-memory schema validation and forward evolution."""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable

from core.contracts import MAX_SIGNED_INT64, CanonicalValue, PersistedEnvelope, _freeze, validate_schema

PayloadValidator = Callable[[CanonicalValue], None]
PayloadEvolution = Callable[[CanonicalValue], object]


class SchemaRegistryError(ValueError): pass
class SchemaRegistrationError(SchemaRegistryError): pass
class UnknownSchemaError(SchemaRegistryError): pass
class UnsupportedSchemaVersionError(SchemaRegistryError): pass
class SchemaValidationError(SchemaRegistryError): pass
class SchemaEvolutionError(SchemaRegistryError): pass


@dataclass(frozen=True, slots=True, order=True)
class SchemaKey:
    schema: str
    version: int

    def __post_init__(self) -> None:
        try:
            validate_schema(self.schema)
        except ValueError as exc:
            raise SchemaRegistrationError("invalid schema") from exc
        if type(self.version) is not int or not 1 <= self.version <= MAX_SIGNED_INT64:
            raise SchemaRegistrationError("invalid schema version")


class SchemaRegistry:
    def __init__(self) -> None:
        self._entries: dict[SchemaKey, tuple[PayloadValidator, PayloadEvolution | None]] = {}
        self._frozen = False

    def register(self, *, schema: str, version: int, validator: PayloadValidator, evolve_from_previous: PayloadEvolution | None = None) -> None:
        if self._frozen:
            raise SchemaRegistrationError("registry is frozen")
        key = SchemaKey(schema, version)
        if key in self._entries or not callable(validator) or (evolve_from_previous is not None and not callable(evolve_from_previous)):
            raise SchemaRegistrationError("invalid or duplicate schema registration")
        self._entries[key] = (validator, evolve_from_previous)

    def freeze(self) -> "SchemaRegistry":
        groups: dict[str, list[SchemaKey]] = {}
        for key in self._entries:
            groups.setdefault(key.schema, []).append(key)
        for schema, keys in groups.items():
            keys.sort()
            if not keys or [key.version for key in keys] != list(range(1, len(keys) + 1)):
                raise SchemaRegistrationError(f"schema {schema} versions must be contiguous")
            for key in keys:
                evolution = self._entries[key][1]
                if (key.version == 1) != (evolution is None):
                    raise SchemaRegistrationError("invalid evolution registration")
        self._frozen = True
        return self

    @property
    def is_frozen(self) -> bool: return self._frozen

    def registrations(self) -> tuple[SchemaKey, ...]: return tuple(sorted(self._entries))

    def _entry(self, schema: str, version: int) -> tuple[PayloadValidator, PayloadEvolution | None]:
        if schema not in {key.schema for key in self._entries}:
            raise UnknownSchemaError(f"unknown schema: {schema}")
        try: return self._entries[SchemaKey(schema, version)]
        except KeyError as exc: raise UnsupportedSchemaVersionError(f"unsupported schema version: {schema}@{version}") from exc

    @staticmethod
    def _validate(validator: PayloadValidator, payload: CanonicalValue) -> None:
        try: validator(_freeze(payload))
        except Exception as exc: raise SchemaValidationError("payload validation failed") from exc

    def validate_envelope(self, envelope: PersistedEnvelope[object], /) -> None:
        if type(envelope) is not PersistedEnvelope:
            raise SchemaValidationError("expected persisted envelope")
        envelope.validate()
        validator, _ = self._entry(envelope.schema, envelope.schema_version)
        self._validate(validator, _freeze(envelope.payload))

    def evolve_payload(self, *, schema: str, from_version: int, to_version: int, payload: object) -> CanonicalValue:
        if type(from_version) is not int or type(to_version) is not int or not 1 <= from_version <= MAX_SIGNED_INT64 or not from_version <= to_version <= MAX_SIGNED_INT64:
            raise SchemaEvolutionError("invalid evolution range")
        value = _freeze(payload)
        validator, _ = self._entry(schema, from_version)
        self._validate(validator, value)
        for version in range(from_version + 1, to_version + 1):
            validator, evolution = self._entry(schema, version)
            if evolution is None:
                raise SchemaEvolutionError("missing evolution")
            try: value = _freeze(evolution(_freeze(value)))
            except Exception as exc: raise SchemaEvolutionError("schema evolution failed") from exc
            self._validate(validator, value)
        return value
