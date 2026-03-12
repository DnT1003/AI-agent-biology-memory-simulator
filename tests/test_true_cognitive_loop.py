import sys, os
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, '.')
import time
from colorama import Fore, Style
from core.engine.cognitive_engine import CognitiveEngine
from core.agent_state import AgentState

print(f"\n{Fore.CYAN}=== KHỞI CHẠY THỬ NGHIỆM TRUE COGNITIVE LOOP (PHASE 12) ==={Style.RESET_ALL}")

engine = CognitiveEngine()
# CognitiveEngine khởi tạo ở IDLE mặc định, chỉ cần start()
engine.autonomous.start() # Bật vòng lặp sinh học với RLock an toàn

print(f"{Fore.GREEN}[Test 1] Kiểm tra hạt giống Semantic Beliefs:{Style.RESET_ALL}")
beliefs = engine.ego.get_active_beliefs(context_query="hạnh phúc")
print(f"Beliefs tìm thấy: {len(beliefs)}")
for b in beliefs:
    print(f"  - {b}")

print(f"\n{Fore.GREEN}[Test 2] Nhồi nhét tương tác để xem Semantic Core có update đúng Overlays không:{Style.RESET_ALL}")
# Force THINKING để update_or_add_memory hoạt động đúng flow
engine.state_machine.force(AgentState.THINKING)
engine.memory_ops.update_or_add_memory(
    user_input="Tôi nghĩ luật lệ là thứ rác rưởi trói buộc con người.",
    perception={'valence': 0.1, 'arousal': 0.8, 'importance': 1.0, 'internal_monologue': 'Người này có vẻ giống mình...'}
)
engine.state_machine.force(AgentState.IDLE)

time.sleep(2) # Chờ GC chạy ngầm 1 nhịp nếu có

print(f"\n{Fore.GREEN}[Test 3] Kiểm tra lại DB xem Memory Mutation còn đè m.content không:{Style.RESET_ALL}")
check = engine.memory.search_memories("luật lệ", top_k=2)
for score, m in check:
    print(f"[{score:.2f}] {m.type} | Content: {m.content}")
    print(f"   Overlays: {m.overlays}")

print(f"\n{Fore.YELLOW}Đang dừng Engine...{Style.RESET_ALL}")
engine.autonomous.stop()
time.sleep(1)
print(f"{Fore.GREEN}Hoàn thành Test!{Style.RESET_ALL}")
