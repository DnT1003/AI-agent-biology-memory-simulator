import uuid
import time
import math
from typing import List, Optional
from dataclasses import dataclass, field
import numpy as np
from colorama import Fore, Style

from config import Config
from components.vector_store import VectorStore
from components.embedder import Embedder

@dataclass
class MemoryTrace:
    content: str
    type: str  # 'episodic', 'semantic', 'core', 'emotional'

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

    def decay(self, stress_level: float):
        """
        Cơ chế Lọc rác Sinh học (Biological Garbage Collection)
        Ký ức nhạt nhẽo (importance thấp, arousal thấp) bay màu cực nhanh.
        Ký ức sốc/quan trọng có thể tồn tại vĩnh viễn (decay_factor tiến về 0).
        """
        if self.is_flashbulb or self.type == 'core' or self.type == 'semantic':
            return # Không phai mờ

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

        # Méo mó cảm xúc
        if not self.is_flashbulb:
            drift = (current_mood - self.valence) * 0.1
            self.valence = max(-1.0, min(1.0, self.valence + drift))

class MemoryManager:
    """Quản lý lớp Bộ nhớ, đóng gói VectorStore tương tự thư viện mem0"""
    def __init__(self, embedder: Embedder):
        self.store = VectorStore()
        self.embedder = embedder

    def add_memory(self, trace: MemoryTrace):
        vector = self.embedder.encode(trace.content)
        self.store.add(trace.id, vector, trace)

    def search_memories(self, query: str, top_k: int = 5) -> List[tuple[float, MemoryTrace]]:
        # Gọi Vector Store để tìm kiếm
        query_vec = self.embedder.encode(query)
        # Kết quả trả về là list of tuples (score, MemoryTrace)
        return self.store.search(query_vec, top_k=top_k)

    def get_all(self) -> List[MemoryTrace]:
        return self.store.get_all_metadata()
    
    def remove(self, memory_id: str):
        self.store.remove(memory_id)

    def enforce_garbage_collection(self):
        """Xóa vĩnh viễn những ký ức đã phai mờ (strength < 0.05). Không còn giới hạn dung lượng cứng!"""
        mems = self.get_all()
        forgotten_count = 0
        for m in mems:
            if m.strength < 0.05 and m.type != 'core':
                self.remove(m.id)
                forgotten_count += 1
                
        if forgotten_count > 0:
            print(f"{Fore.RED}🗑️ [GARBAGE COLLECTION]: Đã quên vĩnh viễn {forgotten_count} sự kiện nhạt nhẽo.{Style.RESET_ALL}")
