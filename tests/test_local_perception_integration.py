import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.engine.cognitive_engine import CognitiveEngine
from colorama import Fore, Style, init
import time

init(autoreset=True)

def test_local_empathy():
    print(f"\n{Fore.CYAN}{'='*60}")
    print(f"  TEST: Tích hợp Local Perception Engine (Phase 8)")
    print(f"{'='*60}{Style.RESET_ALL}")
    
    # Khởi tạo Engine (Sẽ nạp model RoBERTa vào GPU)
    engine = CognitiveEngine()
    
    # Mock user input
    test_inputs = [
        "Chào Aura, tớ đang cảm thấy rất hạnh phúc hôm nay!",
        "Tớ thấy hơi buồn vì trời cứ mưa suốt thôi...",
        "Bạn là một đồ vật vô dụng!",
    ]
    
    for user_text in test_inputs:
        print(f"\n{Fore.WHITE}User: {user_text}")
        old_mood = engine.ego.mood
        
        # Chạy interaction_loop nhưng chỉ quan sát phần Empathy (Phần suy nghĩ LLM sẽ chạy sau)
        # Để test nhanh, ta chỉ gọi phần empathy logic trong InteractionController if possible, 
        # hoặc chạy cả loop vì ta đã mock LLM (nếu cần). 
        # Ở đây ta chạy thật để xem GPU có load không.
        
        engine.interaction.interaction_loop(user_text)
        
        new_mood = engine.ego.mood
        print(f"{Fore.YELLOW}Mood Shift: {old_mood:.2f} -> {new_mood:.2f} (Delta: {new_mood - old_mood:+.2f})")
        
    print(f"\n{Fore.GREEN}{'='*60}")
    print(f"  ✅ TEST HOÀN TẤT. Hãy check log [LOCAL EMPATHY] phía trên.")
    print(f"{'='*60}{Style.RESET_ALL}\n")

if __name__ == "__main__":
    test_local_empathy()
