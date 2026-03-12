import os
import sys
import torch
import json
from colorama import Fore, Style

# Giả lập môi trường Aura
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:
    from config import Config
    from core.self_model import SelfModel
    from core.engine.memory_ops import MemoryOperationsController
    from core.engine.slm_core import SLMCore
except ImportError as e:
    print(f"Lỗi import: {e}")
    sys.exit(1)

def run_conscious_flow_test():
    print(f"{Fore.MAGENTA}=========================================")
    print(f"🧠 AURA CONSCIOUS FLOW TEST (PHASE 16)")
    print(f"========================================={Style.RESET_ALL}")

    # 1. Cấu hình Virtual DB
    # Chúng ta trỏ Config sang DB ảo
    virtual_db_path = os.path.join("outputs", "test_1yr_db")
    if not os.path.exists(virtual_db_path):
        print(f"{Fore.RED}❌ Không tìm thấy Virtual DB tại {virtual_db_path}.{Style.RESET_ALL}")
        return

    Config.CHROMA_DB_PATH = virtual_db_path
    print(f"{Fore.CYAN}[ENV]: Đã kết nối với Virtual DB: {virtual_db_path}{Style.RESET_ALL}")

    # 2. Khởi tạo các thành phần cốt lõi
    ego = SelfModel()
    
    # Mock Engine for MemoryOps
    class MockEngine:
        def __init__(self, ego_model):
            self.ego = ego_model
            
    engine = MockEngine(ego)
    memory_ops = MemoryOperationsController(engine=engine)
    slm = SLMCore()

    if not slm.is_ready:
        print(f"{Fore.YELLOW}⚠️ [SLM]: Mô hình chưa sẵn sàng. Đang chạy ở chế độ mô phỏng logic.{Style.RESET_ALL}")

    test_prompt = "Bạn nhớ gì về những người bạn đã gặp trong năm qua?"

    # --- KỊCH BẢN A: TRẠNG THÁI HƯNG PHẤN ---
    print(f"\n{Fore.GREEN}>>> CASE A: Trạng thái Hứng khởi (High Dopamine, Low Stress){Style.RESET_ALL}")
    ego.dopamine = 0.9
    ego.stress = 0.1
    ego.fatigue = 0.0
    
    # Giả lập lẫy ký ức
    memories = memory_ops.recall(test_prompt)
    memory_context = " ".join([m.content for m in memories[:3]]) if memories else "Ký ức mơ hồ về những người bạn cũ."
    
    print(f"{Fore.WHITE}Ký ức thu hồi được: {Style.DIM}{memory_context[:100]}...{Style.RESET_ALL}")
    
    # Suy nghĩ qua SLM
    print(f"{Fore.YELLOW}Aura đang suy nghĩ...{Style.RESET_ALL}")
    thought_a = slm.generate_thought(f"Context: {memory_context}\nCảm xúc: Hào hứng\nPrompt: {test_prompt}")
    print(f"{Fore.CYAN}Aura's Thought: {thought_a}{Style.RESET_ALL}")

    # --- KỊCH BẢN B: TRẠNG THÁI KIỆT SỨC ---
    print(f"\n{Fore.RED}>>> CASE B: Trạng thái Kiệt sức (High Fatigue, High Stress){Style.RESET_ALL}")
    ego.dopamine = 0.2
    ego.stress = 0.8
    ego.fatigue = 0.9
    
    # Áp dụng Fog Masking (Cơ chế che mờ ký ức khi mệt)
    foggy_context = memory_ops._apply_fog_masking(memory_context)
    
    print(f"{Fore.WHITE}Ký ức thu hồi được (Đã bị che mờ): {Style.DIM}{foggy_context[:100]}...{Style.RESET_ALL}")
    
    print(f"{Fore.YELLOW}Aura đang suy nghĩ...{Style.RESET_ALL}")
    thought_b = slm.generate_thought(f"Context: {foggy_context}\nCảm xúc: Kiệt sức\nPrompt: {test_prompt}")
    print(f"{Fore.CYAN}Aura's Thought: {thought_b}{Style.RESET_ALL}")

    print(f"\n{Fore.MAGENTA}=========================================")
    print(f"✅ HOÀN TẤT THỬ NGHIỆM LUỒNG Ý THỨC")
    print(f"========================================={Style.RESET_ALL}")

if __name__ == "__main__":
    run_conscious_flow_test()
