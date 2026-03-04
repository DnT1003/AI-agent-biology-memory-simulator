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
from .memory_ops import MemoryOpsMixin
from .interaction import InteractionMixin
from .autonomous import AutonomousMixin

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
        self.ego      = ego      or SelfModel()

        # Thread Safety: RLock (reentrant) — cùng thread có thể acquire nhiều lần
        self._ego_lock    = threading.RLock()
        self._memory_lock = threading.RLock()

        self.short_term_buffer: List[str] = []
        self.stm_file_path = "outputs/short_term.json"
        self.last_interaction_time = time.time()
        self.is_thinking = False
        self._running = False  # Lifecycle flag cho background_loop

        from core.tools import get_skill_registry
        self.skills = get_skill_registry()
        self.reader = BackgroundReader(self.llm)
        self.is_reading = False

        if not os.path.exists("outputs"):
            os.makedirs("outputs")

        # B4: Tải lại identity từ lần chạy trước (nếu có)
        with self._ego_lock:
            self.ego.load_state()
        logger.info("CognitiveEngine initialized. Ego state loaded.")

        self.load_short_term_memory()

    def cognitive_tick(self, dt: float = 30.0):
        """
        Module 1: Vòng tick sinh học trung tâm — chạy mỗi dt giây.

        Thứ tự chuẩn của một cognitive architecture:
          1. biological_decay   — sinh lý học luôn tiến hóa theo thời gian
          2. apply_circadian    — nhịp sinh học 24h điều chỉnh mood/fatigue
          3. memory_decay       — ký ức phai dần ngay cả khi không có interaction
          4. garbage_collection — lọc ký ức quá yếu
          5. dump_mind_state    — cập nhật dashboard

        QUAN TRỌNG: Hàm này không cần event hay user input.
        Sinh học chạy dù agent đang ngủ hay không ai nói chuyện.
        """
        try:
            # 1. Biological decay — các chỉ số thay đổi nhẹ mỗi tick
            with self._ego_lock:
                # Fatigue tích lũy chậm theo thời gian
                self.ego.fatigue = min(1.0, self.ego.fatigue + 0.002 * dt / 60)
                # Social need tăng dần khi không có tương tác
                idle_seconds = time.time() - self.last_interaction_time
                if idle_seconds > 60:
                    self.ego.social_need = min(1.0, self.ego.social_need + 0.001 * dt / 60)
                # Stress giảm tự nhiên rất chậm (homeostasis)
                self.ego.stress = max(0.0, self.ego.stress - 0.001 * dt / 60)
                # Curiosity giảm dần nếu đang đọc (đã được thỏa mãn)
                if self.is_reading:
                    self.ego.curiosity = max(0.0, self.ego.curiosity - 0.002 * dt / 60)

            # 2. Circadian rhythm — điều chỉnh mood và fatigue theo giờ
            with self._ego_lock:
                self.ego.apply_circadian_rhythm()

            # 3. Memory decay — ký ức phai dần ngay cả khi không có interaction
            #    Chỉ decay 10% ký ức ngẫu nhiên mỗi tick để tiết kiệm tài nguyên
            with self._memory_lock:
                import random
                mems = self.memory.get_all()
                if mems:
                    sample = random.sample(mems, k=max(1, len(mems) // 10))
                    for m in sample:
                        m.decay(stress_level=self.ego.stress)
                        self.memory.update_memory(m)

            # 4. Garbage collection
            with self._memory_lock:
                self.memory.enforce_garbage_collection()

            # 5. Dump mind state cho Dashboard
            self._dump_mind_state()

        except Exception:
            logger.error("cognitive_tick failed", exc_info=True)

    def shutdown(self):
        """Dừng toàn bộ engine và lưu trạng thái trước khi thoát."""
        self.stop()  # Dừng background_loop từ AutonomousMixin
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
