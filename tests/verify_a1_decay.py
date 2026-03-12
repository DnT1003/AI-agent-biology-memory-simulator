import math
import time
from core.memory import MemoryTrace, MemoryType
from colorama import Fore, Style

def test_ebbinghaus_decay():
    print(f"{Fore.CYAN}--- KIỂM CHỨNG HYBRID DECAY (A1) ---{Style.RESET_ALL}")
    
    # 1. Tạo ký ức mẫu
    mem = MemoryTrace(
        content="User kể về lần đầu tiên đi leo núi Phan Xi Păng.",
        type=MemoryType.EPISODIC,
        valence=0.7, arousal=0.8, importance=0.9
    )
    
    print(f"Ký ức ban đầu: '{mem.content}'")
    print(f"Sức mạnh ban đầu (Strength): {mem.strength:.2f}")

    # 2. Mô phỏng qua 7 ngày với các kịch bản Stress khác nhau
    days = 7
    stress_levels = [0.1, 0.2, 0.5, 0.8, 0.9, 0.3, 0.2] # Dao động
    
    for i in range(days):
        current_stress = stress_levels[i]
        # Giả sử mỗi ngày recall 1 lần để củng cố
        if i % 2 == 0:
            mem.reconsolidate(current_mood=0.5)
            print(f"[Day {i+1}] Đã nhớ lại (Recall). Strength tăng lên: {mem.strength:.4f}")
            
        mem.decay(stress_level=current_stress, elapsed_days=1.0)
        print(f"[Day {i+1}] Decay (Stress: {current_stress:.1f}) -> Strength: {mem.strength:.4f}")

    # 3. Kiểm tra Deep Freeze
    print(f"\n[STEP 2] Kiểm tra Deep Freeze (Importance=0.9, Recall=10)")
    for _ in range(10):
        mem.reconsolidate(current_mood=0.5)
    
    mem.decay(stress_level=0.5) # Nên kích hoạt Deep Freeze
    if mem.is_flashbulb:
        print(f"{Fore.GREEN}✅ DEEP FREEZE HOẠT ĐỘNG: Ký dức đã biến thành Flashbulb.{Style.RESET_ALL}")
    else:
        print(f"{Fore.RED}❌ DEEP FREEZE KHÔNG HOẠT ĐỘNG. Recall count: {mem.recall_count}{Style.RESET_ALL}")

    # 4. Kiểm tra Homeostasis Recovery
    print(f"\n[STEP 3] Kiểm tra Phục hồi Nội môi (Homeostasis)")
    old_strength = mem.strength
    # Tạo ký ức mới để test phục hồi
    mem2 = MemoryTrace(content="Test recovery", type=MemoryType.EPISODIC, valence=0, arousal=0, importance=1.0)
    mem2.strength = 0.5
    mem2.decay(stress_level=0.5, elapsed_days=1.0, homeostasis_recovery=True, nightly_stress_drop=0.5, nightly_fatigue_drop=0.5)
    
    if mem2.strength > 0.5:
        print(f"{Fore.GREEN}✅ HOMEOSTASIS RECOVERY HOẠT ĐỘNG: Strength tăng sau khi ngủ ({mem2.strength:.4f} > 0.5).{Style.RESET_ALL}")
    else:
        print(f"{Fore.YELLOW}⚠️ Cảnh báo: Recovery không đáng kể hoặc không hoạt động. ({mem2.strength:.4f}){Style.RESET_ALL}")

if __name__ == "__main__":
    test_ebbinghaus_decay()
