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
    overlays: List[str] = field(default_factory=list)  # Lớt cảm xúc tích lũy (max 5)

    def __post_init__(self):
        """Invariant enforcement — vào lúc khởi tạo, clamp tất cả số về dải hợp lệ."""
        self.valence    = max(-1.0, min(1.0, self.valence))
        self.arousal    = max(0.0,  min(1.0, self.arousal))
        self.importance = max(0.0,  min(1.0, self.importance))
        self.strength   = max(0.0,  min(1.0, self.strength))

    def decay(self, stress_level: float):
        """
        Cơ chế Lọc rác Sinh học (Biological Garbage Collection)
        Ký ức nhạt nhẽo (importance thấp, arousal thấp) bay màu cực nhanh.
        Ký ức sốc/quan trọng có thể tồn tại vĩnh viễn (decay_factor tiến về 0).
        """
        t = self.type
        if self.is_flashbulb or t == MemoryType.CORE or t == MemoryType.SEMANTIC:
            return  # Không phai mờ

        # Độ lỏng lẻo của ký ức giảm dần nếu có nhiều tầng cảm xúc
        vulnerability = max(0.01, 1.0 - self.importance - (self.emotional_layers * 0.05))
        
        # Công thức phai mờ chịu ảnh hưởng bởi Vulnerability
        decay_factor = Config.FORGETTING_RATE * (1 + stress_level * 0.5) * (vulnerability * 5.0)

        # Keo dính cảm xúc (Chống lãng quên). Các ký ức nhiều tầng được cộng điểm.
        emotional_glue = 0.1 + (self.arousal * 3.0) + (abs(self.valence) * 2.0) + (self.emotional_layers * 0.5)

        # Trừ sức mạnh
        self.strength *= math.exp(-decay_factor / emotional_glue)

    def reconsolidate(self, current_mood: float, is_associative: bool = False):
        """Ký ức bị thay đổi cảm xúc khi nhớ lại (Reconsolidation)"""
        self.last_recalled = time.time()
        self.recall_count += 1
        
        # Hồi sức nhẹ khi vừa được nhớ lại
        # Nếu chỉ là nhớ mang máng (liên tưởng dây chuyền), hồi sức rất ít
        recovery_boost = Config.RECONSOLIDATION_RATE / 4.0 if is_associative else Config.RECONSOLIDATION_RATE
        self.strength = min(1.0, self.strength + recovery_boost)

        # Phase 13: Emotional Inertia (Quán tính cảm xúc)
        # Ký ức CORE có sức kháng cự lớn hơn với mood nhất thời — chống "tẩy não"
        # Flashbulb: hoàn toàn miễn nhiễm (đây là nền tảng bất biến của self)
        if not self.is_flashbulb:
            t = self.type
            if t == MemoryType.CORE:
                drift_factor = 0.02   # Cực kỳ khó thay đổi (5× so với episodic)
            elif t == MemoryType.SEMANTIC:
                drift_factor = 0.05   # Kháng cự vừa phải (2×)
            else:
                drift_factor = 0.1    # EPISODIC / EMOTIONAL: trôi dạt bình thường
            
            drift = (current_mood - self.valence) * drift_factor
            self.valence = max(-1.0, min(1.0, self.valence + drift))
            
            # Emotional Overlays (ghi nhận cảm xúc khi nhớ lại)
            import random
            from datetime import datetime
            MAX_OVERLAYS = 5
            if random.random() < 0.2 and len(self.overlays) < MAX_OVERLAYS:
                date_str = datetime.now().strftime("%d/%m")
                emotional_tag = "rất vui" if current_mood > 0.3 else ("rất buồn" if current_mood < -0.3 else "bình thường")
                self.overlays.append(f"[{date_str}: {emotional_tag}]")
            # Phase 13: Pruning — giữ tối đa 5 overlay gần nhất (mới nhất = quan trọng nhất)
            if len(self.overlays) > MAX_OVERLAYS:
                self.overlays = self.overlays[-MAX_OVERLAYS:]

    def get_display_content(self) -> str:
        """Nội dung đầy đủ để hiển thị hoặc đưa vào prompt, bao gồm overlays."""
        if self.overlays:
            return self.content + " " + " ".join(self.overlays)
        return self.content

class MemoryManager:
    """Quản lý lớp Bộ nhớ, đóng gói VectorStore tương tự thư viện mem0"""
    def __init__(self, embedder: Embedder):
        self.store = VectorStore()
        self.embedder = embedder

    def add_memory(self, trace: MemoryTrace):
        vector = self.embedder.encode(trace.content)
        self.store.add(trace.id, vector, trace)

    def update_memory(self, trace: MemoryTrace):
        """Cập nhật đè lại Metadata vào Vector Store"""
        self.store.update_meta(trace.id, trace)

    def search_memories(self, query: str, top_k: int = 5, min_strength: float = 0.1) -> List[tuple[float, MemoryTrace]]:
        """Tim ky uc theo vector similarity. min_strength duoc day xuong DB layer (Phase 13)."""
        query_vec = self.embedder.encode(query)
        return self.store.search(query_vec, top_k=top_k, min_strength=min_strength)

    def chronological_recall(self, start_time: float, end_time: float, limit: int = 10) -> List[MemoryTrace]:
        return self.store.get_by_time_range(start_time, end_time, limit)

    def get_all(self) -> List[MemoryTrace]:
        return self.store.get_all_metadata()
    
    def remove(self, memory_id: str):
        self.store.remove(memory_id)

    def enforce_garbage_collection(self):
        """Xóa vĩnh viễn những ký ức đã phai mờ (strength < 0.05). Hỗ trợ phân trang chống tràn RAM."""
        forgotten_count = 0
        limit = 50
        offset = 0
        
        while True:
            mems_chunk = self.store.get_all_metadata(limit=limit, offset=offset)
            if not mems_chunk:
                break
                
            for m in mems_chunk:
                # Phase 13: Flashbulb memories cung duoc bao ve khoi GC
                if m.strength < 0.05 and m.type != MemoryType.CORE and not m.is_flashbulb:
                    self.remove(m.id)
                    forgotten_count += 1
            
            offset += limit
                
        if forgotten_count > 0:
            print(f"{Fore.RED}🗑️ [GARBAGE COLLECTION]: Đã quên vĩnh viễn {forgotten_count} sự kiện nhạt nhẽo.{Style.RESET_ALL}")
