import os
import time
from typing import List
from colorama import Fore, Style
from components.llm import LLM
from components.embedder import Embedder
from components.reader import BackgroundReader
from core.memory import MemoryManager
from core.self_model import SelfModel
from .memory_ops import MemoryOpsMixin
from .interaction import InteractionMixin
from .autonomous import AutonomousMixin

class CognitiveEngine(MemoryOpsMixin, InteractionMixin, AutonomousMixin):
    def __init__(self, *, llm=None, embedder=None, memory=None, ego=None):
        """
        Khởi tạo CognitiveEngine với hỗ trợ Dependency Injection (DI).
        Khi chạy thật:    engine = CognitiveEngine()
        Khi viết test:    engine = CognitiveEngine(memory=FakeMemory(), llm=FakeLLM())
        """
        # Dependency Injection: dùng object được truyền vào nếu có,
        # nếu không thì tự tạo mới như bình thường (Production mode).
        self.llm      = llm      or LLM()
        self.embedder = embedder or Embedder()
        self.memory   = memory   or MemoryManager(self.embedder)
        self.ego      = ego      or SelfModel()

        self.short_term_buffer: List[str] = []
        self.stm_file_path = "outputs/short_term.json"
        self.last_interaction_time = time.time()
        self.is_thinking = False
        
        from core.tools import get_skill_registry
        self.skills = get_skill_registry()
        self.reader = BackgroundReader(self.llm)
        self.is_reading = False  # Flag để tránh đọc sách song song
        
        if not os.path.exists("outputs"):
            os.makedirs("outputs")
        self.load_short_term_memory()

    def _dump_mind_state(self):
        """Xuất trạng thái sinh lý và tâm lý ra JSON để Dashboard đọc (Idea 5)"""
        import json
        import time
        try:
            state = {
                "name": self.ego.name,
                "mood": self.ego.mood,
                "stress": self.ego.stress,
                "fatigue": self.ego.fatigue,
                "integrity": self.ego.integrity,
                "curiosity": self.ego.curiosity,
                "social_need": self.ego.social_need,
                "is_stranger": self.ego.is_stranger,
                "current_intimacy": self.ego.current_intimacy,
                "is_identity_crisis": self.ego.is_identity_crisis,
                "active_goals": self.ego.get_active_goals(),
                "timestamp": time.time()
            }
            with open("outputs/mind_state.json", "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            pass
