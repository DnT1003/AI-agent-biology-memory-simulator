import os
import json
import math
import time
import copy
import numpy as np
import requests
from typing import List, Tuple, Any, Dict, Optional
from colorama import Fore, Style
from core.logger import get_logger
from core.memory_context import (
    MemoryAccessError,
    MemoryPrivacy,
    MemoryScope,
)

logger = get_logger("vector_store")
LIFTED_FIELDS = {
    "type",
    "valence",
    "importance",
    "strength",
    "is_flashbulb",
    "is_suppressed",
    "is_consolidated_source",
    "scope",
    "privacy",
}

from components.chroma_rest_client import ChromaRestClient


class MemoryStoreError(RuntimeError):
    """Typed, metadata-safe failure raised for a memory-store operation."""

    def __init__(
        self,
        operation: str,
        *,
        record_count: int = 1,
        cause_type: str = "Exception",
    ) -> None:
        self.operation = operation
        self.record_count = max(0, int(record_count))
        self.cause_type = cause_type
        super().__init__(
            "Memory store operation failed "
            f"(operation={operation}, record_count={self.record_count}, "
            f"cause_type={cause_type})"
        )


class MemoryReadError(MemoryStoreError):
    """A typed backend or decoding failure from a memory read."""


class MemorySchemaError(MemoryReadError):
    """A typed failure for unknown, malformed, or corrupt memory metadata."""


class VectorStore:
    supports_memory_access_policy = True

    def __init__(self):
        from config import Config
        import sys
        from colorama import Fore, Style

        self.client: Any = None

        # ── Risk #3 Fix: Resolve CHROMA_MODE ONCE, enforce single code path ──
        # Precedence: explicit CHROMA_MODE env > USE_CHROMA_SERVER > Python version
        chroma_mode = Config.CHROMA_MODE.strip().lower()
        if not chroma_mode:
            is_py314 = sys.version_info.major == 3 and sys.version_info.minor >= 14
            chroma_mode = "rest" if (Config.USE_CHROMA_SERVER or is_py314) else "embedded"

        if chroma_mode not in ("rest", "embedded"):
            raise ValueError(
                f"[VECTOR STORE] CHROMA_MODE='{chroma_mode}' không hợp lệ. "
                "Chỉ chấp nhận 'rest' hoặc 'embedded'."
            )

        # Guard: nếu USE_CHROMA_SERVER mâu thuẫn với mode, cảnh báo rõ ràng
        if chroma_mode == "embedded" and Config.USE_CHROMA_SERVER:
            print(
                f"{Fore.YELLOW}⚠️ [VECTOR STORE]: CHROMA_MODE=embedded nhưng "
                f"USE_CHROMA_SERVER=True. Ưu tiên CHROMA_MODE → dùng embedded.{Style.RESET_ALL}"
            )
        if chroma_mode == "rest" and not Config.USE_CHROMA_SERVER:
            print(
                f"{Fore.YELLOW}⚠️ [VECTOR STORE]: CHROMA_MODE=rest nhưng "
                f"USE_CHROMA_SERVER=False. Ưu tiên CHROMA_MODE → dùng REST.{Style.RESET_ALL}"
            )

        if chroma_mode == "rest":
            print(f"{Fore.CYAN}🌐 [VECTOR STORE]: Mode=REST → {Config.CHROMA_SERVER_HOST}:{Config.CHROMA_SERVER_PORT}{Style.RESET_ALL}")
            self.client = ChromaRestClient(
                host=Config.CHROMA_SERVER_HOST,
                port=Config.CHROMA_SERVER_PORT
            )
        else:
            print(f"{Fore.CYAN}📁 [VECTOR STORE]: Mode=EMBEDDED → {Config.CHROMA_DB_PATH}{Style.RESET_ALL}")
            try:
                import chromadb
                db_path = getattr(Config, 'CHROMA_DB_PATH', "outputs/chroma_db")
                if not os.path.exists(db_path):
                    os.makedirs(db_path)
                self.client = chromadb.PersistentClient(path=db_path)
            except ImportError:
                print(f"{Fore.RED}❌ [VECTOR STORE]: chromadb not installed. Hãy cài hoặc dùng CHROMA_MODE=rest.{Style.RESET_ALL}")
                raise

        try:
            self.collection = self.client.get_or_create_collection(
                name="aura_long_term_memory",
                metadata={"hnsw:space": "cosine"}
            )
        except Exception as e:
            print(f"{Fore.RED}❌ [VECTOR STORE FATAL]: Could not connect to Chroma Server: {e}{Style.RESET_ALL}")
            print(f"{Fore.RED}   Hệ thống yêu cầu bộ nhớ dài hạn để hoạt động chính xác. Vui lòng chạy start_services.ps1 trước.{Style.RESET_ALL}")
            raise ConnectionError(
                f"Could not connect to Chroma Server at {Config.CHROMA_SERVER_HOST}:{Config.CHROMA_SERVER_PORT}. "
                f"Please run start_services.ps1."
            ) from e

    # ─────────────────────────────────────────────────
    # INTERNAL SERIALIZATION / DESERIALIZATION
    # ─────────────────────────────────────────────────

    def _obj_to_dict(self, obj: Any) -> dict[str, Any]:
        """Serialize schema v6 with canonical, lossless JSON list fields."""
        raw = obj.__dict__.copy()
        try:
            timestamp = float(getattr(obj, 'created_at', 0.0))
        except (TypeError, ValueError, OverflowError):
            raise MemorySchemaError(
                "serialize",
                cause_type="InvalidTimestamp",
            ) from None
        if not math.isfinite(timestamp):
            raise MemorySchemaError(
                "serialize",
                cause_type="InvalidTimestamp",
            )
        meta = {
            "schema_version": "6",
            "timestamp": timestamp,
        }
        known_fields = set(getattr(obj, "__dataclass_fields__", {}))
        for k, v in raw.items():
            # Runtime migration/checkpoint flags are deliberately ephemeral.
            if k.startswith("_"): continue
            if k not in known_fields:
                raise MemorySchemaError(
                    "serialize",
                    cause_type="UnknownSchemaField",
                )
            if v is None: continue
            if isinstance(v, bool):
                meta[k] = int(v)
            elif hasattr(v, "value") and isinstance(v.value, str):
                meta[k] = v.value
            elif isinstance(v, (int, float, str)):
                meta[k] = v
            elif isinstance(v, list):
                if any(not isinstance(item, str) for item in v):
                    raise MemorySchemaError(
                        "serialize",
                        cause_type=f"Invalid{k}List",
                    )
                meta[k] = json.dumps(
                    v,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            else:
                raise MemorySchemaError(
                    "serialize",
                    cause_type="UnsupportedFieldType",
                )
        # Ensure the serializer can never persist a record the strict reader
        # would reject. This validation has no backend side effects.
        self._dict_to_obj(meta)
        return meta

    def _dict_to_obj(self, metadata_dict: Any) -> Any:
        """Decode v1-v6 metadata; reject unknown or corrupt schemas."""
        from core.memory import MemoryTrace, MemoryType, memory_type_from_str

        def schema_error(cause_type: str) -> None:
            raise MemorySchemaError(
                "deserialize",
                cause_type=cause_type,
            ) from None

        def json_string_list(value: Any, field_name: str) -> list[str]:
            if not isinstance(value, str):
                schema_error(f"Invalid{field_name}Encoding")
            try:
                decoded = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                schema_error(f"Invalid{field_name}Json")
            if not isinstance(decoded, list) or any(
                not isinstance(item, str) for item in decoded
            ):
                schema_error(f"Invalid{field_name}List")
            return decoded

        def legacy_string_list(
            value: Any,
            field_name: str,
            *,
            delimiter_fallback: bool = False,
        ) -> list[str]:
            if value is None:
                return []
            if isinstance(value, list):
                decoded = value
            elif isinstance(value, str):
                if not value:
                    return []
                try:
                    candidate = json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    candidate = None
                if isinstance(candidate, list):
                    decoded = candidate
                elif delimiter_fallback:
                    decoded = value.split("\n||\n")
                else:
                    schema_error(f"Invalid{field_name}Json")
            else:
                schema_error(f"Invalid{field_name}Encoding")
            if any(not isinstance(item, str) for item in decoded):
                schema_error(f"Invalid{field_name}List")
            return decoded

        if not isinstance(metadata_dict, dict):
            schema_error("MetadataNotObject")

        try:
            raw_version = metadata_dict.get("schema_version")
            if (
                isinstance(raw_version, bool)
                or not isinstance(raw_version, (str, int))
            ):
                schema_error("InvalidSchemaVersion")
            version = int(raw_version)
            if str(raw_version) != str(version):
                schema_error("InvalidSchemaVersion")
            if version not in {1, 2, 3, 4, 5, 6}:
                schema_error("UnknownSchemaVersion")

            if version <= 4 and "data" in metadata_dict:
                encoded_data = metadata_dict["data"]
                if not isinstance(encoded_data, str):
                    schema_error("InvalidLegacyPayloadEncoding")
                try:
                    data = json.loads(encoded_data)
                except (json.JSONDecodeError, TypeError):
                    schema_error("InvalidLegacyPayloadJson")
                if not isinstance(data, dict):
                    schema_error("LegacyPayloadNotObject")
            else:
                data = metadata_dict.copy()
                data.pop("schema_version", None)
                data.pop("timestamp", None)

            known_fields = set(MemoryTrace.__dataclass_fields__)
            if version == 6:
                timestamp = metadata_dict.get("timestamp")
                if (
                    isinstance(timestamp, bool)
                    or not isinstance(timestamp, (int, float))
                    or not math.isfinite(float(timestamp))
                ):
                    schema_error("InvalidTimestamp")
                unknown_fields = set(data) - known_fields
                if unknown_fields:
                    schema_error("UnknownSchemaField")
                required_fields = {
                    "content", "type", "valence", "arousal", "importance",
                    "id", "created_at", "last_recalled",
                    "strength", "recall_count", "emotional_layers",
                    "is_flashbulb", "is_suppressed", "impact_weight",
                    "overlays", "reality_score", "consolidation_id",
                    "is_consolidated_source", "consolidation_parent_ids",
                    "consolidation_expected_derived_count", "scope", "privacy",
                    "origin_kind", "origin_source", "provenance_parent_ids",
                }
                if not required_fields.issubset(data):
                    schema_error("MissingRequiredField")
                for field_name in (
                    "overlays",
                    "consolidation_parent_ids",
                    "provenance_parent_ids",
                ):
                    data[field_name] = json_string_list(
                        data[field_name],
                        field_name,
                    )
                if len(set(data["consolidation_parent_ids"])) != len(
                    data["consolidation_parent_ids"]
                ):
                    schema_error("DuplicateConsolidationParent")
                if any(
                    not parent_id.strip()
                    for parent_id in data["consolidation_parent_ids"]
                ):
                    schema_error("InvalidConsolidationParent")
                if len(set(data["provenance_parent_ids"])) != len(
                    data["provenance_parent_ids"]
                ):
                    schema_error("DuplicateProvenanceParent")
                if any(
                    not parent_id.strip()
                    for parent_id in data["provenance_parent_ids"]
                ):
                    schema_error("InvalidProvenanceParent")
                raw_type = data.get("type")
                if not isinstance(raw_type, str) or raw_type not in {
                    memory_type.value for memory_type in MemoryType
                }:
                    schema_error("InvalidMemoryType")
                data["type"] = MemoryType(raw_type)

                for field_name, minimum, maximum in (
                    ("valence", -1.0, 1.0),
                    ("arousal", 0.0, 1.0),
                    ("importance", 0.0, 1.0),
                    ("strength", 0.0, 1.0),
                    ("impact_weight", 0.0, 2.0),
                    ("reality_score", 0.0, 1.0),
                ):
                    value = data.get(field_name)
                    if (
                        isinstance(value, bool)
                        or not isinstance(value, (int, float))
                        or not math.isfinite(float(value))
                        or not minimum <= float(value) <= maximum
                    ):
                        schema_error(f"Invalid{field_name}Value")
                for field_name in (
                    "created_at", "last_recalled",
                ):
                    value = data.get(field_name)
                    if (
                        isinstance(value, bool)
                        or not isinstance(value, (int, float))
                        or not math.isfinite(float(value))
                    ):
                        schema_error(f"Invalid{field_name}Value")
                if "last_decayed_at" in data:
                    value = data["last_decayed_at"]
                    if (
                        isinstance(value, bool)
                        or not isinstance(value, (int, float))
                        or not math.isfinite(float(value))
                    ):
                        schema_error("Invalidlast_decayed_atValue")
                for field_name in (
                    "recall_count", "emotional_layers",
                    "consolidation_expected_derived_count",
                ):
                    value = data.get(field_name)
                    if (
                        isinstance(value, bool)
                        or not isinstance(value, int)
                        or value < 0
                    ):
                        schema_error(f"Invalid{field_name}Value")
                for field_name in (
                    "is_flashbulb", "is_suppressed", "is_consolidated_source",
                ):
                    value = data.get(field_name)
                    if not (
                        isinstance(value, bool)
                        or (
                            isinstance(value, int)
                            and not isinstance(value, bool)
                            and value in {0, 1}
                        )
                    ):
                        schema_error(f"Invalid{field_name}Value")
                    data[field_name] = bool(value)
                for field_name in (
                    "content", "id", "consolidation_id", "scope", "privacy",
                    "origin_kind", "origin_source",
                ):
                    if not isinstance(data.get(field_name), str):
                        schema_error(f"Invalid{field_name}Value")
                if not data["id"]:
                    schema_error("InvalidIdValue")
                if not data["origin_kind"].strip():
                    schema_error("InvalidOriginKindValue")
                if not data["origin_source"].strip():
                    schema_error("InvalidOriginSourceValue")
                if float(timestamp) != float(data["created_at"]):
                    schema_error("TimestampCreatedAtMismatch")
                consolidated_at = data.get("consolidated_at")
                if consolidated_at is not None and (
                    isinstance(consolidated_at, bool)
                    or not isinstance(consolidated_at, (int, float))
                    or not math.isfinite(float(consolidated_at))
                ):
                    schema_error("InvalidConsolidatedAtValue")
                source_event_id = data.get("source_event_id")
                if source_event_id is not None and (
                    not isinstance(source_event_id, str)
                    or not source_event_id.strip()
                ):
                    schema_error("InvalidSourceEventId")
            else:
                data["overlays"] = legacy_string_list(
                    data.get("overlays", []),
                    "overlays",
                    delimiter_fallback=True,
                )
                data["consolidation_parent_ids"] = legacy_string_list(
                    data.get("consolidation_parent_ids", []),
                    "consolidation_parent_ids",
                )
                for field_name in (
                    "is_flashbulb", "is_suppressed", "is_consolidated_source",
                ):
                    if field_name in data:
                        data[field_name] = bool(data[field_name])
                if "type" in data:
                    data["type"] = memory_type_from_str(str(data["type"]))
                data["scope"] = "owner"
                data["privacy"] = (
                    "legacy_unknown" if version <= 4 else "standard"
                )
                data["origin_kind"] = "legacy"
                data["origin_source"] = f"schema_v{version}"
                data["source_event_id"] = None
                data["provenance_parent_ids"] = []

            # Start legacy records at migration time.  Falling back to
            # created_at would apply their entire historical age on the first
            # sampled tick and could immediately garbage-collect them.
            legacy_decay_checkpoint = "last_decayed_at" not in data
            if legacy_decay_checkpoint:
                data["last_decayed_at"] = time.time()

            if version < 6:
                data = {k: v for k, v in data.items() if k in known_fields}
            trace = MemoryTrace(**data)
            if legacy_decay_checkpoint:
                trace._last_decay_checkpoint_pending = True
            return trace
        except MemorySchemaError:
            raise
        except Exception as exc:
            logger.error(
                "Memory schema decode failed cause_type=%s",
                type(exc).__name__,
            )
            raise MemorySchemaError(
                "deserialize",
                cause_type=type(exc).__name__,
            ) from None

    # ─────────────────────────────────────────────────
    # WRITE OPERATIONS
    # ─────────────────────────────────────────────────

    def migrate_legacy_metadata(self) -> int:
        """Validate every record and atomically lift schema v1-v5 to v6."""
        try:
            results = self.collection.get(include=["metadatas"])
        except Exception as exc:
            self._raise_read_error("migrate_legacy_metadata.read", exc)
        if not isinstance(results, dict):
            raise MemoryReadError(
                "migrate_legacy_metadata.decode",
                cause_type="MalformedResponse",
            )
        record_ids = results.get("ids")
        metadatas = results.get("metadatas")
        if record_ids == [] and metadatas == []:
            return 0
        if (
            not isinstance(record_ids, list)
            or not isinstance(metadatas, list)
            or len(record_ids) != len(metadatas)
        ):
            raise MemoryReadError(
                "migrate_legacy_metadata.decode",
                cause_type="MalformedResponse",
            )

        # Validate the entire collection first.  No partial migration is
        # attempted when one record has an unknown or corrupt schema.
        legacy_ids: list[str] = []
        migrated_metadatas: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for record_id, raw_metadata in zip(record_ids, metadatas):
            if (
                not isinstance(record_id, str)
                or not record_id
                or record_id in seen_ids
                or not isinstance(raw_metadata, dict)
            ):
                raise MemorySchemaError(
                    "migrate_legacy_metadata.decode",
                    cause_type="MalformedRecord",
                )
            seen_ids.add(record_id)
            trace = self._dict_to_obj(raw_metadata)
            if trace.id != record_id:
                raise MemorySchemaError(
                    "migrate_legacy_metadata.decode",
                    cause_type="RecordIdMismatch",
                )
            if int(raw_metadata.get("schema_version")) < 6:
                legacy_ids.append(record_id)
                migrated_metadatas.append(self._obj_to_dict(trace))

        if not legacy_ids:
            return 0
        try:
            self.collection.update(
                ids=legacy_ids,
                metadatas=migrated_metadatas,
            )
        except Exception as exc:
            self._raise_write_error(
                "migrate_legacy_metadata.update",
                exc,
                record_count=len(legacy_ids),
            )
        return len(legacy_ids)

    @staticmethod
    def _raise_write_error(
        operation: str,
        exc: Exception,
        *,
        record_count: int = 1,
    ) -> None:
        """Log only structural metadata, then raise a stable public error."""
        cause_type = type(exc).__name__
        logger.error(
            "Memory store write failed operation=%s record_count=%d cause_type=%s",
            operation,
            record_count,
            cause_type,
        )
        raise MemoryStoreError(
            operation,
            record_count=record_count,
            cause_type=cause_type,
        ) from None

    @staticmethod
    def _raise_read_error(
        operation: str,
        exc: Exception,
        *,
        record_count: int = 0,
    ) -> None:
        """Log only structural metadata and raise a typed read failure."""
        cause_type = type(exc).__name__
        logger.error(
            "Memory store read failed operation=%s record_count=%d cause_type=%s",
            operation,
            record_count,
            cause_type,
        )
        raise MemoryReadError(
            operation,
            record_count=record_count,
            cause_type=cause_type,
        ) from None

    @staticmethod
    def _normalize_scopes(
        scopes: Any,
        *,
        operation: str,
    ) -> tuple[str, ...]:
        if scopes is None:
            scopes = (MemoryScope.AGENT, MemoryScope.OWNER)
        elif isinstance(scopes, (str, MemoryScope)):
            scopes = (scopes,)
        values: list[str] = []
        try:
            for scope in scopes:
                value = scope.value if isinstance(scope, MemoryScope) else str(scope)
                if value not in {MemoryScope.AGENT.value, MemoryScope.OWNER.value}:
                    raise ValueError
                if value not in values:
                    values.append(value)
        except (TypeError, ValueError):
            raise MemoryAccessError(operation, "invalid_scope") from None
        if not values:
            raise MemoryAccessError(operation, "no_read_scope")
        return tuple(values)

    @classmethod
    def _access_where(cls, scopes: Any, *, operation: str) -> dict[str, Any]:
        scope_values = cls._normalize_scopes(scopes, operation=operation)
        return {
            "$and": [
                {"scope": {"$in": list(scope_values)}},
                {"privacy": {"$eq": MemoryPrivacy.STANDARD.value}},
            ]
        }

    @staticmethod
    def _combine_where(*clauses: Optional[dict[str, Any]]) -> dict[str, Any]:
        flattened: list[dict[str, Any]] = []
        for clause in clauses:
            if not clause:
                continue
            if set(clause) == {"$and"} and isinstance(clause["$and"], list):
                flattened.extend(clause["$and"])
            else:
                flattened.append(clause)
        if len(flattened) == 1:
            return flattened[0]
        return {"$and": flattened}

    @classmethod
    def _validate_trace_access(
        cls,
        trace: Any,
        scopes: Any,
        *,
        operation: str,
    ) -> None:
        allowed = cls._normalize_scopes(scopes, operation=operation)
        scope = getattr(trace, "scope", None)
        privacy = getattr(trace, "privacy", None)
        if scope not in allowed:
            raise MemoryAccessError(operation, "scope_mismatch")
        if privacy != MemoryPrivacy.STANDARD.value:
            raise MemoryAccessError(operation, "privacy_mismatch")

    def _existing_traces(
        self,
        record_ids: List[str],
        *,
        operation: str,
    ) -> dict[str, Any]:
        if not record_ids:
            return {}
        try:
            results = self.collection.get(
                ids=record_ids,
                include=["metadatas"],
            )
        except Exception as exc:
            self._raise_read_error(
                f"{operation}.authorize",
                exc,
                record_count=len(record_ids),
            )
        records = self._decode_metadata_records(
            results,
            operation=f"{operation}.authorize",
            expected_ids=set(record_ids),
        )
        return {record_id: trace for record_id, trace in records}

    def _decode_metadata_records(
        self,
        results: Any,
        *,
        operation: str,
        expected_ids: Optional[set[str]] = None,
    ) -> list[tuple[str, Any]]:
        if not isinstance(results, dict):
            raise MemoryReadError(
                operation,
                cause_type="MalformedResponse",
            )
        found_ids = results.get("ids")
        metadatas = results.get("metadatas")
        if found_ids == [] and metadatas == []:
            return []
        if (
            not isinstance(found_ids, list)
            or not isinstance(metadatas, list)
            or len(found_ids) != len(metadatas)
        ):
            raise MemoryReadError(
                operation,
                cause_type="MalformedResponse",
            )
        decoded: list[tuple[str, Any]] = []
        seen: set[str] = set()
        for found_id, metadata in zip(found_ids, metadatas):
            if (
                not isinstance(found_id, str)
                or not found_id
                or found_id in seen
                or (
                    expected_ids is not None
                    and found_id not in expected_ids
                )
            ):
                raise MemorySchemaError(
                    operation,
                    cause_type="MalformedRecord",
                )
            trace = self._dict_to_obj(metadata)
            if trace.id != found_id:
                raise MemorySchemaError(
                    operation,
                    cause_type="RecordIdMismatch",
                )
            seen.add(found_id)
            decoded.append((found_id, trace))
        return decoded

    @staticmethod
    def _preserve_provenance(meta: Any, existing: Any) -> Any:
        if existing is None:
            return meta
        persisted = copy.copy(meta)
        for field_name in (
            "scope",
            "privacy",
            "origin_kind",
            "origin_source",
            "source_event_id",
            "provenance_parent_ids",
        ):
            value = getattr(existing, field_name)
            if isinstance(value, list):
                value = list(value)
            setattr(persisted, field_name, value)
        return persisted

    @staticmethod
    def _validate_idempotent_create(
        incoming: Any,
        existing: Any,
        *,
        operation: str,
    ) -> None:
        """Accept a create collision only when it denotes the same record."""

        identity_fields = (
            "id",
            "content",
            "type",
            "scope",
            "privacy",
            "origin_kind",
            "origin_source",
            "source_event_id",
            "consolidation_id",
            "consolidation_expected_derived_count",
            "consolidation_parent_ids",
            "provenance_parent_ids",
        )
        for field_name in identity_fields:
            incoming_value = getattr(incoming, field_name, None)
            existing_value = getattr(existing, field_name, None)
            if hasattr(incoming_value, "value"):
                incoming_value = incoming_value.value
            if hasattr(existing_value, "value"):
                existing_value = existing_value.value
            if isinstance(incoming_value, list):
                incoming_value = list(incoming_value)
            if isinstance(existing_value, list):
                existing_value = list(existing_value)
            if incoming_value != existing_value:
                raise MemoryAccessError(operation, "create_collision_mismatch")

    def _authorize_scoped_metas(
        self,
        record_ids: List[str],
        metas: List[Any],
        allowed_scopes: Any,
        *,
        operation: str,
        require_existing: bool = False,
    ) -> dict[str, Any]:
        if len(record_ids) != len(metas):
            raise MemoryAccessError(operation, "batch_shape_mismatch")
        if len(set(record_ids)) != len(record_ids):
            raise MemoryAccessError(operation, "duplicate_record_id")
        for record_id, meta in zip(record_ids, metas):
            if not isinstance(record_id, str) or not record_id:
                raise MemoryAccessError(operation, "invalid_record_id")
            if getattr(meta, "id", None) != record_id:
                raise MemoryAccessError(operation, "record_id_mismatch")
            self._validate_trace_access(
                meta,
                allowed_scopes,
                operation=operation,
            )
        existing = self._existing_traces(record_ids, operation=operation)
        if require_existing and any(
            record_id not in existing for record_id in record_ids
        ):
            raise MemoryAccessError(operation, "record_not_found")
        for trace in existing.values():
            self._validate_trace_access(
                trace,
                allowed_scopes,
                operation=operation,
            )
        return existing

    def _prepare_scoped_metas(
        self,
        record_ids: List[str],
        metas: List[Any],
        allowed_scopes: Any,
        *,
        operation: str,
        require_existing: bool = False,
    ) -> list[Any]:
        existing = self._authorize_scoped_metas(
            record_ids,
            metas,
            allowed_scopes,
            operation=operation,
            require_existing=require_existing,
        )
        prepared: list[Any] = []
        for record_id, meta in zip(record_ids, metas):
            persisted = existing.get(record_id)
            prepared.append(self._preserve_provenance(meta, persisted))
        return prepared

    @staticmethod
    def _vector_list(vector: Any) -> list[Any]:
        return vector.tolist() if isinstance(vector, np.ndarray) else list(vector)

    def _read_created_records(
        self,
        record_ids: List[str],
        expected_vectors: List[list[Any]],
        *,
        operation: str,
    ) -> dict[str, Any]:
        try:
            results = self.collection.get(
                ids=record_ids,
                include=["metadatas", "embeddings"],
            )
        except Exception as exc:
            self._raise_read_error(
                f"{operation}.verify",
                exc,
                record_count=len(record_ids),
            )
        records = self._decode_metadata_records(
            results,
            operation=f"{operation}.verify",
            expected_ids=set(record_ids),
        )
        found_ids = results.get("ids")
        embeddings = results.get("embeddings")
        if isinstance(embeddings, np.ndarray):
            embeddings = embeddings.tolist()
        if (
            not isinstance(embeddings, list)
            or not isinstance(found_ids, list)
            or len(embeddings) != len(found_ids)
        ):
            raise MemoryReadError(
                f"{operation}.verify",
                record_count=len(record_ids),
                cause_type="MalformedResponse",
            )
        expected_by_id = dict(zip(record_ids, expected_vectors))
        for found_id, embedding in zip(found_ids, embeddings):
            try:
                expected = np.asarray(expected_by_id[found_id], dtype=float)
                actual = np.asarray(embedding, dtype=float)
            except (KeyError, TypeError, ValueError, OverflowError):
                raise MemorySchemaError(
                    f"{operation}.verify",
                    cause_type="MalformedEmbedding",
                ) from None
            if (
                expected.ndim != 1
                or actual.ndim != 1
                or expected.shape != actual.shape
                or not np.isfinite(expected).all()
                or not np.isfinite(actual).all()
                or not np.allclose(expected, actual, rtol=1e-5, atol=1e-7)
            ):
                raise MemoryAccessError(operation, "create_collision_mismatch")
        return {record_id: trace for record_id, trace in records}

    def _add_scoped_records(
        self,
        record_ids: List[str],
        vectors: Any,
        metas: List[Any],
        *,
        allowed_scopes: Any,
        operation: str,
    ) -> list[Any]:
        """Create missing records and make exact retries complete no-ops."""
        vector_batch = list(vectors)
        if len(vector_batch) != len(record_ids):
            raise MemoryAccessError(operation, "batch_shape_mismatch")
        existing = self._authorize_scoped_metas(
            record_ids,
            metas,
            allowed_scopes,
            operation=operation,
        )
        canonical: dict[str, Any] = dict(existing)
        missing_ids: list[str] = []
        missing_vectors: list[list[Any]] = []
        missing_metas: list[Any] = []
        for record_id, vector, meta in zip(record_ids, vector_batch, metas):
            persisted = existing.get(record_id)
            if persisted is not None:
                self._validate_idempotent_create(
                    meta,
                    persisted,
                    operation=operation,
                )
                continue
            missing_ids.append(record_id)
            missing_vectors.append(self._vector_list(vector))
            missing_metas.append(meta)

        if missing_ids:
            add_error: Optional[Exception] = None
            try:
                self.collection.add(
                    ids=missing_ids,
                    embeddings=missing_vectors,
                    metadatas=[self._obj_to_dict(meta) for meta in missing_metas],
                )
            except Exception as exc:
                add_error = exc

            # Chroma's ADD may report success while ignoring an ID that won a
            # concurrent race. Always reread metadata and embeddings before
            # acknowledging the create.
            persisted_after = self._read_created_records(
                missing_ids,
                missing_vectors,
                operation=operation,
            )
            if len(persisted_after) != len(missing_ids):
                if add_error is not None:
                    self._raise_write_error(
                        operation,
                        add_error,
                        record_count=len(missing_ids),
                    )
                logger.error(
                    "Memory store create verification failed operation=%s record_count=%d cause_type=%s",
                    operation,
                    len(missing_ids),
                    "IncompleteWrite",
                )
                raise MemoryStoreError(
                    operation,
                    record_count=len(missing_ids),
                    cause_type="IncompleteWrite",
                )
            for record_id, meta in zip(missing_ids, missing_metas):
                persisted = persisted_after[record_id]
                self._validate_trace_access(
                    persisted,
                    allowed_scopes,
                    operation=operation,
                )
                self._validate_idempotent_create(
                    meta,
                    persisted,
                    operation=operation,
                )
            canonical.update(persisted_after)

        return [canonical[record_id] for record_id in record_ids]

    def _upsert_atomic(
        self,
        record_id: str,
        vector: Any,
        meta: Any,
        *,
        operation: str,
    ) -> None:
        try:
            vec = vector.tolist() if isinstance(vector, np.ndarray) else list(vector)
            self.collection.upsert(
                ids=[record_id],
                embeddings=[vec],
                metadatas=[self._obj_to_dict(meta)]  # type: ignore
            )
        except Exception as exc:
            self._raise_write_error(operation, exc)

    def upsert(self, record_id: str, vector: Any, meta: Any):
        """Atomically persist an embedding and its matching metadata."""
        self._upsert_atomic(record_id, vector, meta, operation="upsert")

    def upsert_scoped(
        self,
        record_id: str,
        vector: Any,
        meta: Any,
        *,
        allowed_scopes: Any,
        require_existing: bool = False,
    ) -> Any:
        prepared = self._prepare_scoped_metas(
            [record_id],
            [meta],
            allowed_scopes,
            operation="upsert",
            require_existing=require_existing,
        )
        self._upsert_atomic(record_id, vector, prepared[0], operation="upsert")
        return prepared[0]

    def add(self, record_id: str, vector: Any, meta: Any):
        """Backward-compatible alias for the atomic upsert contract."""
        self._upsert_atomic(record_id, vector, meta, operation="add")

    def add_scoped(
        self,
        record_id: str,
        vector: Any,
        meta: Any,
        *,
        allowed_scopes: Any,
    ) -> Any:
        persisted = self._add_scoped_records(
            [record_id],
            [vector],
            [meta],
            allowed_scopes=allowed_scopes,
            operation="add",
        )
        return persisted[0]

    def add_batch(self, record_ids: List[str], vectors, metas: List[Any]):
        """Batch upsert tối ưu cho tốc độ khi nạp data lớn."""
        try:
            self.collection.upsert(
                ids=record_ids,
                embeddings=[v.tolist() if isinstance(v, np.ndarray) else list(v) for v in vectors],
                metadatas=[self._obj_to_dict(m) for m in metas]  # type: ignore
            )
        except Exception as exc:
            self._raise_write_error(
                "add_batch",
                exc,
                record_count=len(record_ids),
            )

    def add_batch_scoped(
        self,
        record_ids: List[str],
        vectors: Any,
        metas: List[Any],
        *,
        allowed_scopes: Any,
    ) -> list[Any]:
        return self._add_scoped_records(
            record_ids,
            vectors,
            metas,
            allowed_scopes=allowed_scopes,
            operation="add_batch",
        )

    def update_meta(self, record_id: str, meta: Any):
        try:
            self.collection.update(
                ids=[record_id],
                metadatas=[self._obj_to_dict(meta)]  # type: ignore
            )
        except Exception as exc:
            self._raise_write_error("update_meta", exc)

    def update_meta_scoped(
        self,
        record_id: str,
        meta: Any,
        *,
        allowed_scopes: Any,
    ) -> Any:
        prepared = self._prepare_scoped_metas(
            [record_id],
            [meta],
            allowed_scopes,
            operation="update_meta",
            require_existing=True,
        )
        self.update_meta(record_id, prepared[0])
        return prepared[0]

    def update_meta_batch(self, record_ids: List[str], metas: List[Any]):
        try:
            self.collection.update(
                ids=record_ids,
                metadatas=[self._obj_to_dict(meta) for meta in metas]
            )
        except Exception as exc:
            self._raise_write_error(
                "update_meta_batch",
                exc,
                record_count=len(record_ids),
            )

    def update_meta_batch_scoped(
        self,
        record_ids: List[str],
        metas: List[Any],
        *,
        allowed_scopes: Any,
    ) -> list[Any]:
        prepared = self._prepare_scoped_metas(
            record_ids,
            metas,
            allowed_scopes,
            operation="update_meta_batch",
            require_existing=True,
        )
        self.update_meta_batch(record_ids, prepared)
        return prepared

    def upgrade_legacy_provenance_scoped(
        self,
        record_id: str,
        trace: Any,
        *,
        allowed_scopes: Any,
    ) -> Any:
        """Perform the sole allowed one-way upgrade of legacy lineage."""
        operation = "upgrade_legacy_provenance"
        if getattr(trace, "id", None) != record_id:
            raise MemoryAccessError(operation, "record_id_mismatch")
        self._validate_trace_access(
            trace,
            allowed_scopes,
            operation=operation,
        )
        existing_by_id = self._existing_traces(
            [record_id],
            operation=operation,
        )
        existing = existing_by_id.get(record_id)
        if existing is None:
            raise MemoryAccessError(operation, "record_not_found")
        self._validate_trace_access(
            existing,
            allowed_scopes,
            operation=operation,
        )

        expected_parents = list(
            getattr(existing, "consolidation_parent_ids", []) or []
        )
        if (
            not expected_parents
            or len(set(expected_parents)) != len(expected_parents)
            or list(getattr(trace, "consolidation_parent_ids", []) or [])
            != expected_parents
            or getattr(trace, "consolidation_id", None)
            != getattr(existing, "consolidation_id", None)
            or getattr(trace, "scope", None) != getattr(existing, "scope", None)
            or getattr(trace, "privacy", None) != getattr(existing, "privacy", None)
        ):
            raise MemoryAccessError(operation, "lineage_mismatch")

        already_upgraded = (
            existing.origin_kind == "consolidation"
            and existing.origin_source == "sleep"
            and existing.source_event_id is None
            and existing.provenance_parent_ids == expected_parents
        )
        if already_upgraded:
            return existing

        if (
            existing.origin_kind not in {"unknown", "legacy"}
            or existing.source_event_id is not None
            or existing.provenance_parent_ids
            or trace.origin_kind != existing.origin_kind
            or trace.origin_source != existing.origin_source
            or trace.source_event_id is not None
            or trace.provenance_parent_ids
        ):
            raise MemoryAccessError(operation, "provenance_not_legacy")

        upgraded = copy.copy(existing)
        upgraded.origin_kind = "consolidation"
        upgraded.origin_source = "sleep"
        upgraded.source_event_id = None
        upgraded.provenance_parent_ids = list(expected_parents)
        self.update_meta(record_id, upgraded)
        return upgraded

    def update_vector(self, record_id: str, vector: np.ndarray):
        try:
            vec = vector.tolist() if isinstance(vector, np.ndarray) else list(vector)
            self.collection.update(
                ids=[record_id],
                embeddings=[vec]
            )
        except Exception as exc:
            self._raise_write_error("update_vector", exc)

    def remove(self, record_id: str):
        try:
            self.collection.delete(ids=[record_id])
        except Exception as exc:
            self._raise_write_error("remove", exc)

    def remove_scoped(
        self,
        record_id: str,
        *,
        allowed_scopes: Any,
    ) -> None:
        self.remove_batch_scoped([record_id], allowed_scopes=allowed_scopes)

    def remove_batch(self, record_ids: List[str]):
        if not record_ids:
            return
        try:
            self.collection.delete(ids=record_ids)
        except Exception as exc:
            self._raise_write_error(
                "remove_batch",
                exc,
                record_count=len(record_ids),
            )

    def remove_batch_scoped(
        self,
        record_ids: List[str],
        *,
        allowed_scopes: Any,
    ) -> None:
        normalized_ids = list(dict.fromkeys(record_ids))
        if any(not isinstance(record_id, str) or not record_id for record_id in normalized_ids):
            raise MemoryAccessError("remove_batch", "invalid_record_id")
        if not normalized_ids:
            return
        scope_values = self._normalize_scopes(
            allowed_scopes,
            operation="remove_batch",
        )
        existing = self._existing_traces(
            normalized_ids,
            operation="remove_batch",
        )
        for trace in existing.values():
            self._validate_trace_access(
                trace,
                scope_values,
                operation="remove_batch",
            )
        try:
            self.collection.delete(
                ids=normalized_ids,
                where=self._access_where(
                    scope_values,
                    operation="remove_batch",
                ),
            )
        except Exception as exc:
            self._raise_write_error(
                "remove_batch",
                exc,
                record_count=len(normalized_ids),
            )

    def delete_weak_memories(
        self,
        threshold: float = 0.05,
        *,
        allowed_scopes: Any = None,
    ) -> int:
        """Phase 17B: Xóa mem yếu bằng API query thay vì while-loop.
        Giữ lại CORE, SEMANTIC và FLASHBULB.
        """
        scope_values = self._normalize_scopes(
            allowed_scopes,
            operation="delete_weak_memories",
        )
        access_where = self._access_where(
            scope_values,
            operation="delete_weak_memories",
        )
        try:
            results = self.collection.get(
                where=self._combine_where(
                    access_where,
                    {"strength": {"$lt": threshold}},
                ),
                include=["metadatas"]
            )
        except Exception as exc:
            self._raise_write_error(
                "delete_weak_memories.get",
                exc,
                record_count=0,
            )
        weak_records = self._decode_metadata_records(
            results,
            operation="delete_weak_memories.get",
        )
        if not weak_records:
            return 0

        # A derived batch can be durable while its source-marker batch is
        # awaiting retry. Protect those exact parents from GC in that window.
        # Schema-v6 serializes an empty parent list canonically as ``[]``. Use
        # that indexed metadata field instead of scanning every record in the
        # collection merely to find operational manifests.
        manifest_where = self._combine_where(
            access_where,
            {"consolidation_parent_ids": {"$ne": "[]"}},
        )
        try:
            manifest_results = self.collection.get(
                where=manifest_where,
                include=["metadatas"],
            )
        except Exception as exc:
            self._raise_write_error(
                "delete_weak_memories.scan_manifests",
                exc,
                record_count=0,
            )
        manifest_records = self._decode_metadata_records(
            manifest_results,
            operation="delete_weak_memories.scan_manifests",
        )
        protected_parent_ids: set[str] = set()
        for _, trace in manifest_records:
            protected_parent_ids.update(trace.consolidation_parent_ids)
            
        ids_to_drop = []
        for record_id, trace in weak_records:
            # Defense in depth for backends/fakes that do not enforce `where`.
            if trace.privacy != MemoryPrivacy.STANDARD.value: continue
            if trace.scope not in scope_values: continue
            if trace.strength >= threshold: continue
            if record_id in protected_parent_ids: continue
            if trace.is_flashbulb: continue
            if trace.is_consolidated_source: continue
            trace_type = getattr(trace.type, "value", trace.type)
            if trace_type in ["core", "semantic"]: continue
            ids_to_drop.append(record_id)
            
        if ids_to_drop:
            try:
                self.collection.delete(ids=ids_to_drop, where=access_where)
            except Exception as exc:
                self._raise_write_error(
                    "delete_weak_memories",
                    exc,
                    record_count=len(ids_to_drop),
                )
            return len(ids_to_drop)
        return 0

    def clear_all(self):
        logger.warning("clear_all() called! Dropping aura_long_term_memory collection.")
        try:
            self.client.delete_collection(name="aura_long_term_memory")
            self.collection = self.client.get_or_create_collection(
                name="aura_long_term_memory",
                metadata={"hnsw:space": "cosine"}
            )
        except Exception as exc:
            self._raise_write_error("clear_all", exc, record_count=0)

    def reset_collection(self):
        """Xóa vĩnh viễn collection hiện tại để tạo lại với kích thước vector mới (đổi model)"""
        print(f"{Fore.RED}⚠️ [VECTOR STORE]: Đang xóa toàn bộ bộ nhớ cũ để đồng bộ kích thước vector mới...{Style.RESET_ALL}")
        logger.warning("reset_collection() called! Destroying memory schema.")
        try:
            self.client.delete_collection(name="aura_long_term_memory")
        except Exception as exc:
            self._raise_write_error(
                "reset_collection.delete",
                exc,
                record_count=0,
            )
        try:
            self.collection = self.client.get_or_create_collection(
                name="aura_long_term_memory",
                metadata={"hnsw:space": "cosine"}
            )
        except Exception as exc:
            self._raise_write_error(
                "reset_collection.recreate",
                exc,
                record_count=0,
            )

    # ─────────────────────────────────────────────────
    # READ OPERATIONS
    # ─────────────────────────────────────────────────

    def get_all_metadata(self, limit: Optional[int] = None, offset: Optional[int] = None,
                         min_strength: Optional[float] = None,
                         read_scopes: Any = None) -> List[Any]:
        """Lấy metadata có hỗ trợ phân trang (Pagination) và pre-filter bằng DB query.
        
        Phase 13: min_strength filter được áp dụng ở tầng DB (dùng lifted metadata)
        thay vì load hết rồi filter trong Python.
        """
        scope_values = self._normalize_scopes(
            read_scopes,
            operation="get_all_metadata",
        )
        access_where = self._access_where(
            scope_values,
            operation="get_all_metadata",
        )
        kwargs = {"where": access_where}
        if limit is not None:
            kwargs["limit"] = limit
        if offset is not None:
            kwargs["offset"] = offset

        # Phase 13: Pre-filter ở DB level bằng lifted 'strength' field
        if min_strength is not None:
            kwargs["where"] = self._combine_where(
                access_where,
                {"strength": {"$gte": min_strength}},
            )

        try:
            results = self.collection.get(**kwargs)
        except Exception as exc:
            self._raise_read_error(
                "get_all_metadata",
                exc,
                record_count=0,
            )
        if not isinstance(results, dict):
            raise MemoryReadError(
                "get_all_metadata.decode",
                cause_type="MalformedResponse",
            )
        metadatas = results.get('metadatas') if results else None
        if metadatas is None or metadatas == []:
            return []
        if not isinstance(metadatas, list):
            raise MemoryReadError(
                "get_all_metadata.decode",
                cause_type="MalformedResponse",
            )

        objs = []
        for meta_dict in metadatas:
            trace = self._dict_to_obj(meta_dict)
            self._validate_trace_access(
                trace,
                scope_values,
                operation="get_all_metadata",
            )
            objs.append(trace)
        return objs

    def get_by_time_range(
        self,
        start_time: float,
        end_time: float,
        limit: int = 10,
        read_scopes: Any = None,
    ) -> List[Any]:
        """Truy xuất các vector theo dòng thời gian (chronological recall)"""
        scope_values = self._normalize_scopes(
            read_scopes,
            operation="get_by_time_range",
        )
        access_where = self._access_where(
            scope_values,
            operation="get_by_time_range",
        )
        try:
            results = self.collection.get(
                where=self._combine_where(
                    access_where,
                    {"timestamp": {"$gte": float(start_time)}},
                    {"timestamp": {"$lte": float(end_time)}},
                ),
                limit=limit
            )
        except Exception as exc:
            self._raise_read_error("get_by_time_range", exc)
        if not isinstance(results, dict):
            raise MemoryReadError(
                "get_by_time_range.decode",
                cause_type="MalformedResponse",
            )
        metadatas = results.get('metadatas') if results else None
        if metadatas is None or metadatas == []:
            return []
        if not isinstance(metadatas, list):
            raise MemoryReadError(
                "get_by_time_range.decode",
                cause_type="MalformedResponse",
            )
            
        objs = []
        for meta_dict in metadatas:
            trace = self._dict_to_obj(meta_dict)
            self._validate_trace_access(
                trace,
                scope_values,
                operation="get_by_time_range",
            )
            objs.append(trace)
             
        objs.sort(key=lambda x: getattr(x, 'created_at', 0.0), reverse=True)
        return objs

    def search(self, query_vec: np.ndarray, top_k: int = 5,
               min_strength: Optional[float] = None,
               read_scopes: Any = None) -> List[Tuple[float, Any]]:
        """Tìm kiếm vector tương đồng.
        
        Phase 13: Có thể pre-filter bằng 'strength' lifted field trước khi tìm vector,
        tránh kéo ký ức yếu ớt không liên quan vào kết quả.
        """
        scope_values = self._normalize_scopes(
            read_scopes,
            operation="search",
        )
        access_where = self._access_where(
            scope_values,
            operation="search",
        )
        try:
            count = self.collection.count()
        except Exception as exc:
            self._raise_read_error("search.count", exc)
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise MemoryReadError(
                "search.count",
                cause_type="MalformedResponse",
            )
        if count == 0:
            return []

        vec_to_query = query_vec.tolist() if hasattr(query_vec, 'tolist') else query_vec
        query_kwargs: dict[str, Any] = {
            "query_embeddings": [vec_to_query],
            "n_results": min(top_k, count),
            "include": ["metadatas", "distances"],
            "where": access_where,
        }

        # Phase 13: Pre-filter tại DB thay vì post-filter tại Python
        if min_strength is not None:
            query_kwargs["where"] = self._combine_where(
                access_where,
                {"strength": {"$gte": min_strength}},
            )
            
        try:
            results = self.collection.query(**query_kwargs)
        except Exception as exc:
            self._raise_read_error("search.query", exc)
        if not isinstance(results, dict):
            raise MemoryReadError(
                "search.decode",
                cause_type="MalformedResponse",
            )
        
        ids = results.get('ids')
        distances = results.get('distances')
        metadatas = results.get('metadatas')
        
        if ids == [[]] and distances == [[]] and metadatas == [[]]:
            return []
        if (
            not isinstance(ids, list) or len(ids) != 1
            or not isinstance(ids[0], list)
            or not isinstance(distances, list) or len(distances) != 1
            or not isinstance(distances[0], list)
            or not isinstance(metadatas, list) or len(metadatas) != 1
            or not isinstance(metadatas[0], list)
            or not (
                len(ids[0]) == len(distances[0]) == len(metadatas[0])
            )
        ):
            raise MemoryReadError(
                "search.decode",
                cause_type="MalformedResponse",
            )

        formatted_results = []
        for i in range(len(ids[0])):
            distance = distances[0][i]
            if (
                isinstance(distance, bool)
                or not isinstance(distance, (int, float))
                or not math.isfinite(float(distance))
            ):
                raise MemoryReadError(
                    "search.decode",
                    cause_type="MalformedDistance",
                )
            similarity = max(0.0, min(1.0, 1.0 - distance))
            meta_obj = self._dict_to_obj(metadatas[0][i])
            self._validate_trace_access(
                meta_obj,
                scope_values,
                operation="search",
            )
            formatted_results.append((similarity, meta_obj))

        return formatted_results
