import os
import time
import math
import threading
from typing import List
from colorama import Fore, Style
from components.llm import LLM
from components.embedder import Embedder
from components.reader import BackgroundReader
from core.memory import MemoryManager
from core.self_model import SelfModel
from core.logger import get_logger
from config import Config
from .memory_ops import MemoryOpsMixin
from .interaction import InteractionMixin
from .autonomous import AutonomousMixin
from core.agent_state import StateMachine, AgentState

logger = get_logger("cognitive_engine")


class CognitiveEngine(MemoryOpsMixin, InteractionMixin, AutonomousMixin):
    def __init__(self, *, llm=None, embedder=None, memory=None, ego=None):
        """
        Khởi tạo CognitiveEngine với hỗ trợ Dependency Injection (DI).
        Khi chạy thật:    engine = CognitiveEngine()
        Khi viết test:    engine = CognitiveEngine(memory=FakeMemory(), llm=FakeLLM())
        """
        self.llm      = llm      or LLM()
        self.embedder = embedder or Embedder()
        self.memory   = memory   or MemoryManager(self.embedder)
        self.ego      = ego      or SelfModel(memory_manager=self.memory)

        # Thread Safety: RLock (reentrant) — cùng thread có thể acquire nhiều lần
        self._ego_lock    = threading.RLock()
        self._memory_lock = threading.RLock()

        self.short_term_buffer: List[str] = []
        self.stm_file_path = Config.STM_FILE  # Phase 15: dung Config thay hardcode
        self.last_interaction_time = time.time()
        
        # Phase 12: Áp dụng StateMachine thực sự.
        self.state_machine = StateMachine()

        from core.tools import get_skill_registry
        self.skills = get_skill_registry()
        self.reader = BackgroundReader(self.llm)

        if not os.path.exists("outputs"):
            os.makedirs("outputs")

        # B4: Tải lại identity từ lần chạy trước (nếu có)
        with self._ego_lock:
            self.ego.load_state()
            self.ego.init_core_semantics()
        logger.info("CognitiveEngine initialized. Ego state loaded and core semantics seeded.")

        self.load_short_term_memory()

    def cognitive_tick(self, dt: float = 30.0):
        """
        Module 1: Vòng tick sinh học trung tâm — chạy mỗi dt giây.
        """
        try:
            # 1 & 2. Biological decay + Circadian rhythm
            # Gộp thành 1 Big RLock cho Ego để đảm bảo tính Atomic (không hở sườn giữa chừng)
            with self._ego_lock:
                # Phase 14: Non-linear Metabolism (Exponential Biological Curves)
                # Fatigue tang nhanh hon khi da met (kieu quadratic resistance)
                # f_new = f + rate * dt * (1 + f) — cang met cang mat suc nhanh
                fatigue_rate = 0.002 / 60  # baseline per second
                self.ego.fatigue = min(1.0, self.ego.fatigue + fatigue_rate * dt * (1 + self.ego.fatigue * 0.5))

                idle_seconds = time.time() - self.last_interaction_time
                if idle_seconds > 60:
                    self.ego.social_need = min(1.0, self.ego.social_need + 0.001 * dt / 60)

                # Stress giam theo exponential decay (half-life model, khong tuyen tinh)
                # s_new = s * exp(-decay_rate * dt)
                stress_decay = math.exp(-0.002 * dt / 60)
                self.ego.stress = max(0.0, self.ego.stress * stress_decay)

                if self.state_machine.state == AgentState.READING:
                    self.ego.curiosity = max(0.0, self.ego.curiosity - 0.002 * dt / 60)
                # Phase 13: Metabolic Cost — tieu ton nang luong khi suy nghi
                # Moi LLM call o trang thai THINKING se dot fatigue truoc khi tra loi
                if self.state_machine.state == AgentState.THINKING:
                    self.ego.fatigue = min(1.0, self.ego.fatigue + 0.005 * dt / 60)

                self.ego.apply_circadian_rhythm()

            # 3 & 4. Memory decay + Garbage collection
            # Gộp thành 1 Big RLock cho Memory 
            with self._memory_lock:
                import random
                mems = self.memory.get_all()
                if mems:
                    sample = random.sample(mems, k=max(1, len(mems) // 10))
                    for m in sample:
                        m.decay(stress_level=self.ego.stress)
                        self.memory.update_memory(m)
                
                # GC phân trang (đã sửa ở memory.py) được gọi an toàn trong lock này
                self.memory.enforce_garbage_collection()

            # 5. Dump mind state cho Dashboard
            self._dump_mind_state()

        except Exception:
            logger.error("cognitive_tick failed", exc_info=True)

    def shutdown(self):
        """Dừng toàn bộ engine và lưu trạng thái trước khi thoát."""
        self.stop()  # Dừng background_loop từ AutonomousMixin
        if hasattr(self, 'reader') and getattr(self.reader, 'stop', None):
            self.reader.stop()
        with self._ego_lock:
            self.ego.save_state()
        logger.info("CognitiveEngine shutdown complete. Ego state saved.")

    def _dump_mind_state(self):
        """Xuất trạng thái sinh lý và tâm lý ra JSON để Dashboard đọc (Idea 5)"""
        import json
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
        except Exception:
            logger.warning("Failed to dump mind state", exc_info=True)
