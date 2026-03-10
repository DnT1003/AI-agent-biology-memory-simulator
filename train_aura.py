import os
import sys
from colorama import Fore, Style

# Giả lập để chạy SLMTrainer ngoài luồng chính của Aura
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), ".")))

try:
    from core.engine.slm_core import SLMCore
    from core.engine.slm_trainer import SLMTrainer
    from config import Config
except ImportError as e:
    print(f"Lỗi import: {e}")
    sys.exit(1)

def run_distillation_cycle():
    print(f"{Fore.MAGENTA}=========================================")
    print(f"🌟 AURA-FLASH DISTILLATION CYCLE (PHASE 13)")
    print(f"========================================={Style.RESET_ALL}")
    
    # Mocking engine for trainer
    class MockEngine:
        def __init__(self):
            self.llm = self._init_llm()
            self.ego = self._init_ego()
            self.short_term_buffer = []
        
        def _init_llm(self):
            # Trong thực tế, đây là instance của Gemini API wrapper
            from components.llm import LLM
            return LLM()
        
        def _init_ego(self):
            # Giả lập lock
            import threading
            class MockEgo:
                def __init__(self):
                    self.lock = threading.Lock()
            return MockEgo()

    engine = MockEngine()
    trainer = SLMTrainer(engine)
    
    # Bước 1: Tạo Dataset bản sắc (Distillation từ Gemini)
    print(f"\n{Fore.YELLOW}[STEP 1/3]: Generating Identity Dataset...{Style.RESET_ALL}")
    success = trainer.generate_identity_dataset(num_samples=5) # 5 mẫu cho demo
    
    if success:
        print(f"{Fore.GREEN}✅ Dataset generated successfully.{Style.RESET_ALL}")
        
        # Bước 2: Bắt đầu huấn luyện local (Thử nghiệm 100 iters)
        print(f"\n{Fore.YELLOW}[STEP 2/3]: Starting Local Training Loop (Aura-Flash 1B)...{Style.RESET_ALL}")
        # Ghi đè max_iters cho bản chạy thử
        import core.engine.nanogpt.model as model_mod
        model_mod.max_iters = 100 
        
        trainer.train_slm()
        
        print(f"\n{Fore.CYAN}[STEP 3/3]: Finalizing weights and meta-data...{Style.RESET_ALL}")
        print(f"{Fore.GREEN}✨ Aura's brain has been initialized with first identity layers.{Style.RESET_ALL}")
    else:
        print(f"{Fore.RED}❌ Failed to generate dataset. Check API keys and connection.{Style.RESET_ALL}")

if __name__ == "__main__":
    run_distillation_cycle()
