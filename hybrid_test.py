import os
import time
from config import Config
from colorama import Fore, Style
from core.engine.slm_core import SLMCore
from core.engine.slm_trainer import SLMTrainer
from components.llm import LLM

class MockEngine:
    def __init__(self):
        self.ego = type('Ego', (), {'lock': type('Lock', (), {'__enter__': lambda x: None, '__exit__': lambda x, y, z, a: None})(), 'fatigue': 0.0})()
        self.short_term_buffer = ["User: Hello", "Aura: Hi"]
        self.llm = LLM(self.ego)
        self.SLM_DIR = Config.SLM_DIR

def test_hybrid_flow():
    print(f"{Fore.CYAN}=== VERIFYING HYBRID & SLM COMPONENTS (ISOLATED) ==={Style.RESET_ALL}")
    engine = MockEngine()
    
    # 1. Test Switching Logic
    print(f"\n[Test 1]: LLM Switching Logic")
    llm = engine.llm
    print(f"Default: Should use local? {llm._should_use_local('hello')}")
    print(f"Command /local: Should use local? {llm._should_use_local('/local hello')}")
    engine.ego.fatigue = 0.8
    print(f"Fatigue 0.8: Should use local? {llm._should_use_local('hello')}")
    
    # 2. Test SLM Thought Generation
    print(f"\n[Test 2]: SLM Native Thought Generation")
    slm = SLMCore()
    if slm.is_ready:
        thought = slm.generate_thought("Hôm nay")
        print(f"Native Thought: {thought}")
    else:
        print("SLM not ready (expected if no .pt file yet)")
    
    # 3. Test SLM Trainer Distillation (Simulated)
    print(f"\n[Test 3]: SLM Trainer Dataset Generation")
    trainer = SLMTrainer(engine)
    # We won't actually call Gemini here to avoid API costs/errors in test, 
    # but we verify the file path and logic exists.
    print(f"Training file path: {trainer.training_file}")

if __name__ == "__main__":
    test_hybrid_flow()
