import uuid
import time
import math
from enum import Enum
from typing import List, Optional, Union
from dataclasses import dataclass, field
import numpy as np
from colorama import Fore, Style
from config import Config
from components.vector_store import MemoryStoreError, VectorStore
from components.embedder import Embedder
from core.memory_context import (
    MemoryAccessContext,
    MemoryAccessError,
    MemoryPrivacy,
    current_memory_context,
)
from core.writer_lease import ProcessWriterLease


class MemoryType(str, Enum):
    """Enum cho loại ký ức (kế thừa str — tương thích bật BACKWARD với ChromaDB đã lưu)."""
    EPISODIC  = "episodic"
    SEMANTIC  = "semantic"
    CORE      = "core"
    EMOTIONAL = "emotional"


def memory_type_from_str(s: str) -> MemoryType:
    """Safe conversion từ string → MemoryType. Fallback về EPISODIC nếu không nhận ra."""
    try:
        return MemoryType(s.lower())
    except ValueError:
        return MemoryType.EPISODIC


@dataclass
class MemoryTrace:
    content: str
    type: Union[MemoryType, str]  # MemoryType enum (hoặc string bảo hưng ChromaDB cũ)

    # TRỌNG SỐ (WEIGHTS)
    valence: float  # -1.0 (Buồn/Đau) -> 1.0 (Vui/Sướng)
    arousal: float  # 0.0 (Tĩnh) -> 1.0 (Động/Sốc)
    importance: float  # Độ quan trọng chủ quan

    # META DATA
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: float = field(default_factory=time.time)
    last_recalled: float = field(default_factory=time.time)
    # Checkpoint thời gian thật cho decay tăng dần; None tương thích DB cũ.
    last_decayed_at: Optional[float] = None
    strength: float = 1.0  # Sức mạnh ký ức (1.0 = Tươi mới, 0.0 = Quên sạch)
    recall_count: int = 0  # Số lần được nhớ lại (để tính toán rủi ro bị méo mó)
    emotional_layers: int = 1 # Số tầng cảm xúc (Càng nhiều tầng, càng khó quên)
    is_flashbulb: bool = False # Ký ức in hằn không bao giờ phai
    is_suppressed: bool = False # Thẻ "Gấu Trắng" - Cố quên nhưng lại càng nhớ
    impact_weight: float = 1.0 # Trọng số tác động đến Mood (Phase 19)
    overlays: List[str] = field(default_factory=list)  # Lớp cảm xúc tích lũy (max 5)
    reality_score: float = 1.0 # [Tính năng 4] Điểm thực tại (1.0 = Thật, 0.3 = Ảo/Suy diễn)

    # Lossless semantic consolidation lineage. Sources remain queryable and
    # protected from automatic pruning after their derived memories are safe.
    consolidation_id: str = ""
    consolidated_at: Optional[float] = None
    is_consolidated_source: bool = False
    # Durable manifest copied onto every derived trace. This lets a later
    # process finish the exact source batch without asking the LLM again.
    consolidation_parent_ids: List[str] = field(default_factory=list)
    consolidation_expected_derived_count: int = 0

    # Minimal provenance contract for schema v6. Access-control filtering is
    # intentionally deferred; these fields only make origin and ownership
    # explicit and round-trippable.
    scope: str = "owner"
    privacy: str = "standard"
    origin_kind: str = "unknown"
    origin_source: str = "unknown"
    source_event_id: Optional[str] = None
    provenance_parent_ids: List[str] = field(default_factory=list)

    def __post_init__(self):
        """Invariant enforcement — vào lúc khởi tạo, clamp tất cả số về dải hợp lệ."""
        self.valence       = max(-1.0, min(1.0, self.valence))
        self.arousal       = max(0.0,  min(1.0, self.arousal))
        self.importance    = max(0.0,  min(1.0, self.importance))
        self.strength      = max(0.0,  min(1.0, self.strength))
        self.impact_weight = max(0.0,  min(2.0, self.impact_weight))
        self.reality_score = max(0.0,  min(1.0, self.reality_score))
        if (
            self.last_decayed_at is None
            or isinstance(self.last_decayed_at, bool)
            or not isinstance(self.last_decayed_at, (int, float))
            or not math.isfinite(float(self.last_decayed_at))
        ):
            self.last_decayed_at = float(self.created_at)
        else:
            self.last_decayed_at = float(self.last_decayed_at)

        if (
            self.consolidated_at is not None
            and (
                isinstance(self.consolidated_at, bool)
                or not isinstance(self.consolidated_at, (int, float))
                or not math.isfinite(float(self.consolidated_at))
            )
        ):
            self.consolidated_at = None
        elif self.consolidated_at is not None:
            self.consolidated_at = float(self.consolidated_at)
        self.consolidation_id = str(self.consolidation_id or "")
        self.is_consolidated_source = bool(self.is_consolidated_source)
        parent_ids = (
            self.consolidation_parent_ids
            if isinstance(self.consolidation_parent_ids, (list, tuple))
            else []
        )
        self.consolidation_parent_ids = list(dict.fromkeys(
            str(parent_id)
            for parent_id in parent_ids
            if isinstance(parent_id, str) and parent_id
        ))
        try:
            expected_count = int(self.consolidation_expected_derived_count)
        except (TypeError, ValueError, OverflowError):
            expected_count = 0
        self.consolidation_expected_derived_count = max(0, expected_count)

        if self.scope not in {"agent", "owner"}:
            raise ValueError("invalid memory scope")
        if self.privacy not in {"standard", "legacy_unknown"}:
            raise ValueError("invalid memory privacy")
        if not isinstance(self.origin_kind, str) or not self.origin_kind.strip():
            raise ValueError("invalid memory origin kind")
        if not isinstance(self.origin_source, str) or not self.origin_source.strip():
            raise ValueError("invalid memory origin source")
        if self.source_event_id is not None and (
            not isinstance(self.source_event_id, str)
            or not self.source_event_id.strip()
        ):
            raise ValueError("invalid memory source event id")
        if not isinstance(self.provenance_parent_ids, list) or any(
            not isinstance(parent_id, str) or not parent_id.strip()
            for parent_id in self.provenance_parent_ids
        ):
            raise ValueError("invalid memory provenance parents")
        if len(set(self.provenance_parent_ids)) != len(
            self.provenance_parent_ids
        ):
            raise ValueError("duplicate memory provenance parent")

    def decay(self, stress_level: float, elapsed_days: float = 0.0,
              homeostasis_recovery: bool = False, nightly_stress_drop: float = 0.0, nightly_fatigue_drop: float = 0.0):
        """
        Cơ chế Lãng quên Hybrid Ebbinghaus + Deep Freeze + Homeostasis Recovery (Phase 18)

        elapsed_days defaults to zero deliberately: callers that omit elapsed
        time must never advance a memory by an implicit simulated day.
        """
        t = self.type
        if self.is_flashbulb or t == MemoryType.CORE or t == MemoryType.SEMANTIC:
            return  # Không phai mờ

        # --- 1. Cơ chế Deep Freeze (Phase 18) ---
        # Ký ức rất quan trọng & được nhắc lại nhiều lần sẽ biến thành Flashbulb (Nhớ trọn đời)
        if self.importance >= 0.9 and self.recall_count >= 10:
            self.is_flashbulb = True
            print(f"❄️ [DEEP FREEZE]: Ký ức '{self.content[:30]}...' đã hóa thạch vĩnh viễn trong não bộ.")
            return

        try:
            elapsed_days = float(elapsed_days)
        except (TypeError, ValueError):
            elapsed_days = 0.0
        if not math.isfinite(elapsed_days) or elapsed_days < 0.0:
            elapsed_days = 0.0

        # --- 2. Hybrid Ebbinghaus Decay ---
        # Tính R (Độ ổn định / Retrievability)
        base_R = 1.0 + (self.importance * 10.0) + (self.arousal * 5.0) + (abs(self.valence) * 3.0)
        current_R = base_R * (1.2 ** self.recall_count) * (1.1 ** self.emotional_layers)
        
        # Stress Penalty
        stress_penalty = 1.0 - (stress_level * 0.5) 
        effective_R = current_R * stress_penalty

        # Suy giảm theo hàm e mũ
        S_0 = self.strength # Strength từ ngày hôm trước
        decayed_strength = self.strength * math.exp(-elapsed_days / (effective_R + 1e-6))

        # --- 3. Homeostasis Recovery (Phục hồi nội môi - Phase 18) ---
        if homeostasis_recovery and (nightly_stress_drop > 0 or nightly_fatigue_drop > 0):
            # Tăng hệ số phục hồi (0.05 -> 0.15) để đảm bảo giấc ngủ thực sự củng cố trí nhớ quan trọng
            recovery_factor = (nightly_stress_drop + nightly_fatigue_drop) * 0.15 * self.importance
            total_recovery = recovery_factor * elapsed_days
            decayed_strength = min(1.0, decayed_strength + total_recovery)
            
        self.strength = decayed_strength

        # --- 4. Reality Probability Drift (Phase ALIFE OS) ---
        # Khi thời gian trôi, ranh giới Thực/Ảo sẽ mờ dần, hội tụ về 0.5 (nghi ngờ)
        if hasattr(self, 'reality_score'):
            drift_to_center = (0.5 - self.reality_score) * 0.05 * elapsed_days
            self.reality_score += drift_to_center

    def reconsolidate(self, current_mood: float, is_associative: bool = False,
                      count_recall: bool = True) -> bool:
        """Ký ức bị thay đổi cảm xúc khi nhớ lại (Reconsolidation).

        ``count_recall=False`` dành cho suy nghĩ miên man/rumination: nghĩ lại
        thụ động không được tính là một lần ôn luyện chủ động, nếu không ký ức
        bị nghiền ngẫm sẽ nhanh chóng "hóa thạch" (Deep Freeze) và bất tử.
        """
        self.last_recalled = time.time()
        if count_recall:
            self.recall_count += 1
        
        recovery_boost = Config.RECONSOLIDATION_RATE / 4.0 if is_associative else Config.RECONSOLIDATION_RATE
        self.strength = min(1.0, self.strength + recovery_boost)

        needs_rewrite = False
        if not self.is_flashbulb:
            t = self.type
            if t == MemoryType.CORE:
                drift_factor = 0.02
            elif t == MemoryType.SEMANTIC:
                drift_factor = 0.05
            else:
                drift_factor = 0.1
            
            mood_diff = current_mood - self.valence
            # Nếu chênh lệch quá lớn (Phase 17B True False Memories)
            if abs(mood_diff) > 0.6 and t != MemoryType.CORE:
                needs_rewrite = True
                
            # [Tính năng 4: False Memory Trigger] Ký ức mờ ảo (0.4-0.6) có nguy cơ rất cao bị ghi đè nhầm
            is_uncertain = hasattr(self, 'reality_score') and 0.4 <= self.reality_score <= 0.6
            if is_uncertain and not needs_rewrite:
                import random
                if random.random() < 0.3: # Lệch lạc 30% khi ký ức đã mù mờ
                    needs_rewrite = True
                    self.reality_score = 0.8 # Một khi bị nhớ nhầm (ngữ nghĩa hóa), người ta sẽ tự thuyết phục mình đó là Hàng Thật!

            drift = mood_diff * drift_factor
            self.valence = max(-1.0, min(1.0, self.valence + drift))
            
            import random
            from datetime import datetime
            MAX_OVERLAYS = 5
            if random.random() < 0.2 and len(self.overlays) < MAX_OVERLAYS:
                date_str = datetime.now().strftime("%d/%m")
                emotional_tag = "rất vui" if current_mood > 0.3 else ("rất buồn" if current_mood < -0.3 else "bình thường")
                self.overlays.append(f"[{date_str}: {emotional_tag}]")
            
            if len(self.overlays) > MAX_OVERLAYS:
                self.overlays = self.overlays[-MAX_OVERLAYS:]

        return needs_rewrite

    def get_display_content(self) -> str:
        """Nội dung đầy đủ để hiển thị hoặc đưa vào prompt, bao gồm overlays."""
        if self.overlays:
            return self.content + " " + " ".join(self.overlays)
        return self.content

class MemoryManager:
    """Quản lý lớp Bộ nhớ, đóng gói VectorStore tương tự thư viện mem0"""
    def __init__(self, embedder: Embedder):
        import threading

        self.lock = threading.RLock()
        self._writer_lease = ProcessWriterLease(
            Config.MEMORY_WRITER_LEASE_FILE
        ).acquire()
        try:
            # Lease acquisition deliberately precedes all VectorStore setup so
            # a losing process cannot connect, migrate, or mutate the store.
            self.store = VectorStore()
        except BaseException:
            self._writer_lease.close()
            raise
        self.embedder = embedder
        self._access_migration_complete = False

    def close(self) -> None:
        """Release this process's writer ownership after callers quiesce it."""

        with self.lock:
            lease = getattr(self, "_writer_lease", None)
            if lease is None:
                return
            lease.close()
            self._writer_lease = None

    @staticmethod
    def _require_access(operation: str) -> MemoryAccessContext:
        context = current_memory_context()
        if context.private_ephemeral:
            raise MemoryAccessError(operation, "private_ephemeral")
        if not context.read_scopes:
            raise MemoryAccessError(operation, "no_read_scope")
        return context

    @staticmethod
    def _read_scope_values(context: MemoryAccessContext) -> tuple[str, ...]:
        return tuple(scope.value for scope in context.read_scopes)

    @classmethod
    def _write_scope_values(cls, context: MemoryAccessContext) -> tuple[str, ...]:
        if context.write_scope is not None:
            return (context.write_scope.value,)
        return cls._read_scope_values(context)

    @classmethod
    def _creation_scope_values(
        cls,
        context: MemoryAccessContext,
        *,
        operation: str,
    ) -> tuple[str, ...]:
        if context.write_scope is None:
            raise MemoryAccessError(operation, "write_scope_required")
        return cls._write_scope_values(context)

    @classmethod
    def _validate_write_trace(
        cls,
        trace: MemoryTrace,
        context: MemoryAccessContext,
        *,
        operation: str,
    ) -> None:
        if getattr(trace, "scope", None) not in cls._write_scope_values(context):
            raise MemoryAccessError(operation, "scope_mismatch")
        if getattr(trace, "privacy", None) != MemoryPrivacy.STANDARD.value:
            raise MemoryAccessError(operation, "privacy_mismatch")

    @staticmethod
    def _stamp_new_provenance(
        trace: MemoryTrace,
        context: MemoryAccessContext,
    ) -> None:
        trace.origin_kind = context.origin_kind
        trace.origin_source = context.origin_source
        trace.source_event_id = context.source_event_id

    @staticmethod
    def _sync_persisted_trace(
        target: MemoryTrace,
        persisted: object,
        *,
        operation: str,
    ) -> None:
        if not isinstance(persisted, MemoryTrace):
            raise MemoryStoreError(
                f"{operation}.decode",
                cause_type="MalformedResponse",
            )
        if persisted is target:
            return
        canonical = {
            key: (list(value) if isinstance(value, list) else value)
            for key, value in persisted.__dict__.items()
        }
        target.__dict__.clear()
        target.__dict__.update(canonical)

    def _store_supports_access_policy(self) -> bool:
        return getattr(
            self.store,
            "supports_memory_access_policy",
            False,
        ) is True

    def _policy_store_method(self, method_name: str, *, operation: str):
        if not self._store_supports_access_policy():
            raise MemoryAccessError(operation, "unsupported_store")
        method = getattr(self.store, method_name, None)
        if not callable(method):
            raise MemoryAccessError(operation, "unsupported_store")
        return method

    def _ensure_access_migration(self, *, operation: str) -> None:
        migrate = self._policy_store_method(
            "migrate_legacy_metadata",
            operation=operation,
        )
        if getattr(self, "_access_migration_complete", False):
            return
        migrate()
        self._access_migration_complete = True

    def _encode_for_write(self, content: str):
        try:
            vector = self.embedder.encode(content)
        except Exception as exc:
            from core.logger import get_logger
            cause_type = type(exc).__name__
            get_logger("memory").error(
                "Memory embedding failed operation=embed cause_type=%s",
                cause_type,
            )
            raise MemoryStoreError(
                "embed",
                cause_type=cause_type,
            ) from None
        if isinstance(vector, list):
            vector = vector[0] if vector else np.array([])
        return vector

    def _require_embedding_allowed(
        self,
        context: MemoryAccessContext,
        *,
        operation: str,
    ) -> None:
        if context.local_only and getattr(
            self.embedder,
            "requires_network",
            True,
        ) is not False:
            raise MemoryAccessError(
                operation,
                "local_embedding_unavailable",
            )

    def add_memory(self, trace: MemoryTrace):
        context = self._require_access("add_memory")
        self._require_embedding_allowed(context, operation="add_memory")
        allowed_scopes = self._creation_scope_values(
            context,
            operation="add_memory",
        )
        self._validate_write_trace(trace, context, operation="add_memory")
        self._stamp_new_provenance(trace, context)
        with self.lock:
            self._ensure_access_migration(operation="add_memory")
            add_scoped = self._policy_store_method(
                "add_scoped",
                operation="add_memory",
            )
            vector = self._encode_for_write(trace.content)
            persisted = add_scoped(
                trace.id,
                vector,
                trace,
                allowed_scopes=allowed_scopes,
            )
            self._sync_persisted_trace(
                trace,
                persisted,
                operation="add_memory",
            )

    def add_memories(self, traces: List[MemoryTrace]):
        """Persist a group through exactly one vector-store batch call."""
        context = self._require_access("add_memories")
        self._require_embedding_allowed(context, operation="add_memories")
        allowed_scopes = self._creation_scope_values(
            context,
            operation="add_memories",
        )
        batch = list(traces)
        if not batch:
            return
        for trace in batch:
            self._validate_write_trace(
                trace,
                context,
                operation="add_memories",
            )
        for trace in batch:
            self._stamp_new_provenance(trace, context)
        with self.lock:
            self._ensure_access_migration(operation="add_memories")
            add_batch_scoped = self._policy_store_method(
                "add_batch_scoped",
                operation="add_memories",
            )
            vectors = [self._encode_for_write(trace.content) for trace in batch]
            record_ids = [trace.id for trace in batch]
            persisted_batch = add_batch_scoped(
                record_ids,
                vectors,
                batch,
                allowed_scopes=allowed_scopes,
            )
            if not isinstance(persisted_batch, list) or len(
                persisted_batch
            ) != len(batch):
                raise MemoryStoreError(
                    "add_batch.decode",
                    record_count=len(batch),
                    cause_type="MalformedResponse",
                )
            for trace, persisted in zip(batch, persisted_batch):
                self._sync_persisted_trace(
                    trace,
                    persisted,
                    operation="add_memories",
                )

    def update_memory(self, trace: MemoryTrace):
        """Cập nhật đè lại Metadata vào Vector Store"""
        context = self._require_access("update_memory")
        self._validate_write_trace(trace, context, operation="update_memory")
        allowed_scopes = self._write_scope_values(context)
        with self.lock:
            self._ensure_access_migration(operation="update_memory")
            update_meta_scoped = self._policy_store_method(
                "update_meta_scoped",
                operation="update_memory",
            )
            persisted = update_meta_scoped(
                trace.id,
                trace,
                allowed_scopes=allowed_scopes,
            )
            self._sync_persisted_trace(
                trace,
                persisted,
                operation="update_memory",
            )

    def update_memories(self, traces: List[MemoryTrace]):
        """Persist one metadata transition for a complete source group."""
        context = self._require_access("update_memories")
        batch = list(traces)
        if not batch:
            return
        for trace in batch:
            self._validate_write_trace(
                trace,
                context,
                operation="update_memories",
            )
        allowed_scopes = self._write_scope_values(context)
        with self.lock:
            self._ensure_access_migration(operation="update_memories")
            update_meta_batch_scoped = self._policy_store_method(
                "update_meta_batch_scoped",
                operation="update_memories",
            )
            record_ids = [trace.id for trace in batch]
            persisted_batch = update_meta_batch_scoped(
                record_ids,
                batch,
                allowed_scopes=allowed_scopes,
            )
            if not isinstance(persisted_batch, list) or len(
                persisted_batch
            ) != len(batch):
                raise MemoryStoreError(
                    "update_memories.decode",
                    record_count=len(batch),
                    cause_type="MalformedResponse",
                )
            for trace, persisted in zip(batch, persisted_batch):
                self._sync_persisted_trace(
                    trace,
                    persisted,
                    operation="update_memories",
                )

    def upgrade_legacy_provenance(self, trace: MemoryTrace) -> MemoryTrace:
        """One-way upgrade for a verified M2.1 consolidation manifest."""
        context = self._require_access("upgrade_legacy_provenance")
        if (
            context.origin_kind != "consolidation"
            or context.origin_source != "sleep"
        ):
            raise MemoryAccessError(
                "upgrade_legacy_provenance",
                "invalid_upgrade_context",
            )
        self._validate_write_trace(
            trace,
            context,
            operation="upgrade_legacy_provenance",
        )
        allowed_scopes = self._write_scope_values(context)
        with self.lock:
            self._ensure_access_migration(operation="upgrade_legacy_provenance")
            upgrade_scoped = self._policy_store_method(
                "upgrade_legacy_provenance_scoped",
                operation="upgrade_legacy_provenance",
            )
            upgraded = upgrade_scoped(
                trace.id,
                trace,
                allowed_scopes=allowed_scopes,
            )
        trace.origin_kind = upgraded.origin_kind
        trace.origin_source = upgraded.origin_source
        trace.source_event_id = upgraded.source_event_id
        trace.provenance_parent_ids = list(upgraded.provenance_parent_ids)
        return trace

    def upsert_memory(self, trace: MemoryTrace):
        """Persist a content-derived vector and metadata in one store call."""
        context = self._require_access("upsert_memory")
        self._require_embedding_allowed(context, operation="upsert_memory")
        self._validate_write_trace(trace, context, operation="upsert_memory")
        allowed_scopes = self._write_scope_values(context)
        with self.lock:
            self._ensure_access_migration(operation="upsert_memory")
            upsert_scoped = self._policy_store_method(
                "upsert_scoped",
                operation="upsert_memory",
            )
            vector = self._encode_for_write(trace.content)
            persisted = upsert_scoped(
                trace.id,
                vector,
                trace,
                allowed_scopes=allowed_scopes,
                require_existing=True,
            )
            self._sync_persisted_trace(
                trace,
                persisted,
                operation="upsert_memory",
            )

    def search_memories(
        self,
        query: str,
        top_k: int = 5,
        min_strength: float = 0.1,
        *,
        writable_only: bool = False,
    ) -> List[tuple[float, MemoryTrace]]:
        """Tim ky uc theo vector similarity. min_strength duoc day xuong DB layer (Phase 13)."""
        context = self._require_access("search_memories")
        self._require_embedding_allowed(context, operation="search_memories")
        read_scopes = (
            self._write_scope_values(context)
            if writable_only
            else self._read_scope_values(context)
        )
        with self.lock:
            self._ensure_access_migration(operation="search_memories")
            search = self._policy_store_method(
                "search",
                operation="search_memories",
            )
            query_vec = self.embedder.encode(query)
            if isinstance(query_vec, list):
                query_vec = query_vec[0] if query_vec else np.array([])
            return search(
                query_vec,
                top_k=top_k,
                min_strength=min_strength,
                read_scopes=read_scopes,
            )

    def chronological_recall(self, start_time: float, end_time: float, limit: int = 10) -> List[MemoryTrace]:
        context = self._require_access("chronological_recall")
        read_scopes = self._read_scope_values(context)
        with self.lock:
            self._ensure_access_migration(operation="chronological_recall")
            get_by_time_range = self._policy_store_method(
                "get_by_time_range",
                operation="chronological_recall",
            )
            return get_by_time_range(
                start_time,
                end_time,
                limit,
                read_scopes=read_scopes,
            )

    def get_all(self) -> List[MemoryTrace]:
        context = self._require_access("get_all")
        read_scopes = self._read_scope_values(context)
        with self.lock:
            self._ensure_access_migration(operation="get_all")
            get_all_metadata = self._policy_store_method(
                "get_all_metadata",
                operation="get_all",
            )
            return get_all_metadata(read_scopes=read_scopes)
    
    def remove(self, memory_id: str):
        context = self._require_access("remove")
        allowed_scopes = self._write_scope_values(context)
        with self.lock:
            self._ensure_access_migration(operation="remove")
            remove_scoped = self._policy_store_method(
                "remove_scoped",
                operation="remove",
            )
            remove_scoped(
                memory_id,
                allowed_scopes=allowed_scopes,
            )

    def remove_many(self, memory_ids: List[str]):
        """Delete a deterministic group while holding the manager lock."""
        context = self._require_access("remove_many")
        allowed_scopes = self._write_scope_values(context)
        record_ids = list(dict.fromkeys(
            memory_id
            for memory_id in memory_ids
            if isinstance(memory_id, str) and memory_id
        ))
        if not record_ids:
            return
        with self.lock:
            self._ensure_access_migration(operation="remove_many")
            remove_batch_scoped = self._policy_store_method(
                "remove_batch_scoped",
                operation="remove_many",
            )
            remove_batch_scoped(
                record_ids,
                allowed_scopes=allowed_scopes,
            )

    def enforce_garbage_collection(self):
        """Phase 17B: Xóa vĩnh viễn những ký ức đã phai mờ (strength < 0.05) bằng DB API query."""
        context = self._require_access("enforce_garbage_collection")
        allowed_scopes = self._write_scope_values(context)
        with self.lock:
            self._ensure_access_migration(operation="enforce_garbage_collection")
            try:
                delete_weak_memories = self._policy_store_method(
                    "delete_weak_memories",
                    operation="enforce_garbage_collection",
                )
                forgotten_count = delete_weak_memories(
                    threshold=0.05,
                    allowed_scopes=allowed_scopes,
                )
                if forgotten_count > 0:
                    print(f"{Fore.RED}🗑️ [GARBAGE COLLECTION]: Đã quên vĩnh viễn {forgotten_count} sự kiện nhạt nhẽo.{Style.RESET_ALL}")
            except MemoryStoreError:
                raise
            except MemoryAccessError:
                raise
            except Exception as e:
                print(f"{Fore.RED}Lỗi GC: {e}{Style.RESET_ALL}")
