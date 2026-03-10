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
from .memory_ops import MemoryOperationsController
from .interaction import InteractionController
from .autonomous import AutonomousController
from .perception import PerceptionController
from .slm_core import SLMCore
from core.agent_state import StateMachine, AgentState

logger = get_logger("cognitive_engine")


class CognitiveEngine:
    def __init__(self, *, llm=None, embedder=None, memory=None, ego=None):
        """
        Khởi tạo CognitiveEngine với hỗ trợ Dependency Injection (DI).
        Khi chạy thật:    engine = CognitiveEngine()
        Khi viết test:    engine = CognitiveEngine(memory=FakeMemory(), llm=FakeLLM())
        """
        self.embedder = embedder or Embedder()
        self.memory   = memory   or MemoryManager(self.embedder)
        self.ego      = ego      or SelfModel(memory_manager=self.memory)
        self.llm      = llm      or LLM(ego=self.ego)

        # Thread Safety: Standardizing on object-level locks (ego.lock, memory.lock)
        # to prevent deadlock and ensure compatibility with Python 3.14 free-threading.
        
        self.short_term_buffer: List[str] = []
        self.stm_file_path = Config.STM_FILE  # Phase 15: dung Config thay hardcode
        self.last_interaction_time = time.time()
        
        # Phase 12: Áp dụng StateMachine thực sự.
        self.state_machine = StateMachine()

        from core.tools import get_skill_registry
        self.skills = get_skill_registry()
        self.skills.load()  # Phase 6: Nạp độ thông thạo từ ổ cứng
        self.reader = BackgroundReader(self.llm)

        from core.world_graph import WorldGraph
        self.world_graph = WorldGraph()

        from core.value_system import ValueSystem
        self.value_system = ValueSystem()

        from core.local_perception import LocalPerception
        self.local_perception = LocalPerception()

        self.memory_ops = MemoryOperationsController(self)
        self.perception_ops = PerceptionController(self)
        self.interaction = InteractionController(self)
        self.autonomous = AutonomousController(self)
        self.slm = SLMCore()

        if not os.path.exists("outputs"):
            os.makedirs("outputs")

        # B4: Tải lại identity từ lần chạy trước (nếu có)
        with self.ego.lock:
            self.ego.load_state()
            self.ego.init_core_semantics()
        logger.info("CognitiveEngine initialized. Ego state loaded and core semantics seeded.")

        self.memory_ops.load_short_term_memory()

    def cognitive_tick(self, dt: float = 30.0):
        """
        Module 1: Vòng tick sinh học trung tâm — chạy mỗi dt giây.
        """
        try:
            # 1 & 2. Biological decay + Circadian rhythm
            # Using self.ego.lock to ensure atomic biological updates
            with self.ego.lock:
                # Phase 14: Non-linear Metabolism (Exponential Biological Curves)
                # Fatigue tang nhanh hon khi da met (kieu quadratic resistance)
                # f_new = f + rate * dt * (1 + f) — cang met cang mat suc nhanh
                fatigue_rate = 0.002 / 60  # baseline per second
                self.ego.fatigue = min(1.0, self.ego.fatigue + fatigue_rate * dt * (1 + self.ego.fatigue * 0.5))

                idle_seconds = time.time() - self.last_interaction_time
                self.ego.apply_biological_decay(dt, idle_seconds)

                # Stress giam theo exponential decay (half-life model, khong tuyen tinh)
                # s_new = s * exp(-decay_rate * dt)
                stress_decay = math.exp(-0.002 * dt / 60)
                self.ego.stress = max(0.0, self.ego.stress * stress_decay)

                # Phase 8: Metabolism (Energy & ATP)
                # Energy hồi phục tự nhiên (0.01 mỗi phút)
                self.ego.energy = min(1.0, self.ego.energy + 0.01 * dt / 60)
                # ATP hồi phục nhanh hơn khi IDLE (không làm việc nặng)
                atp_recovery_rate = 0.05 if self.state_machine.state == AgentState.IDLE else 0.01
                self.ego.atp_level = min(1.0, self.ego.atp_level + atp_recovery_rate * dt / 60)

                if self.state_machine.state == AgentState.READING:
                    self.ego.curiosity = max(0.0, self.ego.curiosity - 0.002 * dt / 60)
                    # Đọc sách tiêu tốn Energy
                    self.ego.energy = max(0.0, self.ego.energy - 0.005 * dt / 60)

                # Giảm nhẹ trừ gốc (0.005 -> 0.001) chờ tích hợp Token-based cost bên trong `llm.py`
                if self.state_machine.state == AgentState.THINKING:
                    self.ego.fatigue = min(1.0, self.ego.fatigue + 0.001 * dt / 60)
                    # Suy nghĩ sâu (LLM) tiêu tốn ATP mạnh
                    self.ego.atp_level = max(0.0, self.ego.atp_level - 0.05 * dt / 60)

                # Phân hệ 9 (Sprint D): Storage Pressure (Áp lực sinh thái)
                # Nếu ChromaDB quá lớn, Aura sẽ cảm thấy "nặng đầu" (Tăng stress)
                try:
                    def get_dir_size(path):
                        total = 0
                        with os.scandir(path) as it:
                            for entry in it:
                                if entry.is_file():
                                    total += entry.stat().size
                                elif entry.is_dir():
                                    total += get_dir_size(entry.path)
                        return total
                    
                    if os.path.exists(Config.CHROMA_DB_PATH):
                        db_size = get_dir_size(Config.CHROMA_DB_PATH)
                        if db_size > Config.MAX_STORAGE_SIZE:
                            pressure = (db_size - Config.MAX_STORAGE_SIZE) / (100 * 1024 * 1024) # Mỗi 100MB dư thêm 1 stress unit
                            storage_stress = min(0.3, pressure * 0.1) # Max penalty 0.3
                            self.ego.stress = min(1.0, self.ego.stress + storage_stress)
                            if storage_stress > 0.05:
                                print(f"{Fore.LIGHTRED_EX}🧠 [STORAGE PRESSURE]: Bộ nhớ quá tải ({db_size/1024/1024:.1f}MB). Aura cảm thấy nặng đầu...{Style.RESET_ALL}")
                except Exception as e:
                    logger.debug(f"Failed to calculate storage pressure: {e}")

                self.ego.apply_circadian_rhythm()

            # 3 & 4. Memory decay + Garbage collection
            # Using self.memory.lock for atomic memory operations
            with self.memory.lock:
                import random
                mems = self.memory.get_all()
                if mems:
                    sample = random.sample(list(mems), k=max(1, len(mems) // 10))
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
        with self.ego.lock:
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
