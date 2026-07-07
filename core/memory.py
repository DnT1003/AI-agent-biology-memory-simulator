import uuid
import time
import math
from enum import Enum
from typing import List, Optional, Union
from dataclasses import dataclass, field
import numpy as np
from colorama import Fore, Style
from config import Config
from components.vector_store import VectorStore
from components.embedder import Embedder


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
    strength: float = 1.0  # Sức mạnh ký ức (1.0 = Tươi mới, 0.0 = Quên sạch)
    recall_count: int = 0  # Số lần được nhớ lại (để tính toán rủi ro bị méo mó)
    emotional_layers: int = 1 # Số tầng cảm xúc (Càng nhiều tầng, càng khó quên)
    is_flashbulb: bool = False # Ký ức in hằn không bao giờ phai
    is_suppressed: bool = False # Thẻ "Gấu Trắng" - Cố quên nhưng lại càng nhớ
    impact_weight: float = 1.0 # Trọng số tác động đến Mood (Phase 19)
    overlays: List[str] = field(default_factory=list)  # Lớp cảm xúc tích lũy (max 5)
    reality_score: float = 1.0 # [Tính năng 4] Điểm thực tại (1.0 = Thật, 0.3 = Ảo/Suy diễn)

    def __post_init__(self):
        """Invariant enforcement — vào lúc khởi tạo, clamp tất cả số về dải hợp lệ."""
        self.valence       = max(-1.0, min(1.0, self.valence))
        self.arousal       = max(0.0,  min(1.0, self.arousal))
        self.importance    = max(0.0,  min(1.0, self.importance))
        self.strength      = max(0.0,  min(1.0, self.strength))
        self.impact_weight = max(0.0,  min(2.0, self.impact_weight))
        self.reality_score = max(0.0,  min(1.0, self.reality_score))

    def decay(self, stress_level: float, elapsed_days: float = 1.0, 
              homeostasis_recovery: bool = False, nightly_stress_drop: float = 0.0, nightly_fatigue_drop: float = 0.0):
        """
        Cơ chế Lãng quên Hybrid Ebbinghaus + Deep Freeze + Homeostasis Recovery (Phase 18)
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

    def reconsolidate(self, current_mood: float, is_associative: bool = False) -> bool:
        """Ký ức bị thay đổi cảm xúc khi nhớ lại (Reconsolidation)"""
        self.last_recalled = time.time()
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
        self.store = VectorStore()
        self.embedder = embedder
        self.lock = threading.RLock()

    def add_memory(self, trace: MemoryTrace):
        with self.lock:
            vector = self.embedder.encode(trace.content)
            if isinstance(vector, list):
                vector = vector[0] if vector else np.array([])
            self.store.add(trace.id, vector, trace)

    def update_memory(self, trace: MemoryTrace):
        """Cập nhật đè lại Metadata vào Vector Store"""
        with self.lock:
            self.store.update_meta(trace.id, trace)

    def search_memories(self, query: str, top_k: int = 5, min_strength: float = 0.1) -> List[tuple[float, MemoryTrace]]:
        """Tim ky uc theo vector similarity. min_strength duoc day xuong DB layer (Phase 13)."""
        with self.lock:
            query_vec = self.embedder.encode(query)
            if isinstance(query_vec, list):
                query_vec = query_vec[0] if query_vec else np.array([])
            return self.store.search(query_vec, top_k=top_k, min_strength=min_strength)

    def chronological_recall(self, start_time: float, end_time: float, limit: int = 10) -> List[MemoryTrace]:
        with self.lock:
            return self.store.get_by_time_range(start_time, end_time, limit)

    def get_all(self) -> List[MemoryTrace]:
        with self.lock:
            return self.store.get_all_metadata()
    
    def remove(self, memory_id: str):
        with self.lock:
            self.store.remove(memory_id)

    def enforce_garbage_collection(self):
        """Phase 17B: Xóa vĩnh viễn những ký ức đã phai mờ (strength < 0.05) bằng DB API query."""
        with self.lock:
            try:
                forgotten_count = self.store.delete_weak_memories(threshold=0.05)
                if forgotten_count > 0:
                    print(f"{Fore.RED}🗑️ [GARBAGE COLLECTION]: Đã quên vĩnh viễn {forgotten_count} sự kiện nhạt nhẽo.{Style.RESET_ALL}")
            except Exception as e:
                print(f"{Fore.RED}Lỗi GC: {e}{Style.RESET_ALL}")
