import os
import time
from typing import List
from colorama import Fore, Style
from components.llm import LLM
from components.embedder import Embedder
from core.memory import MemoryManager
from core.self_model import SelfModel
from .memory_ops import MemoryOpsMixin
from .interaction import InteractionMixin
from .autonomous import AutonomousMixin

class CognitiveEngine(MemoryOpsMixin, InteractionMixin, AutonomousMixin):
    def __init__(self):
        self.llm = LLM()
        self.embedder = Embedder()
        self.memory = MemoryManager(self.embedder)
        self.ego = SelfModel()
        self.short_term_buffer: List[str] = []
        self.stm_file_path = "outputs/short_term.json"
        self.last_interaction_time = time.time()
        self.is_thinking = False
        
        from core.tools import get_skill_registry
        self.skills = get_skill_registry()
        
        if not os.path.exists("outputs"):
            os.makedirs("outputs")
        self.load_short_term_memory()
