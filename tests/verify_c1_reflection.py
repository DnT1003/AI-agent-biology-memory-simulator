import sys
from unittest.mock import MagicMock, patch
import json
from colorama import Fore, Style

# Mock modules
sys.modules['core.world_graph'] = MagicMock()
sys.modules['core.local_perception'] = MagicMock()
sys.modules['core.tools'] = MagicMock()
sys.modules['components.reader'] = MagicMock()

from core.engine.cognitive_engine import CognitiveEngine
from core.memory import MemoryTrace

def test_reflection_evolution():
    print(f"{Fore.CYAN}--- KIỂM CHỨNG IDENTITY EVOLUTION (C1) ---{Style.RESET_ALL}")
    
    # 1. Setup Engine
    mock_llm = MagicMock()
    mock_embedder = MagicMock()
    engine = CognitiveEngine(llm=mock_llm, embedder=mock_embedder)
    
    # 2. Giả lập STM đủ để phản tư
    engine.short_term_buffer = [
        "User: Chào Aura, bạn thấy việc giúp đỡ mọi người thế nào?",
        "Aura: Tớ thấy rất hạnh phúc khi được giúp đỡ bạn.",
        "User: Tớ trân trọng sự trung thực của bạn.",
        "Aura: Cảm ơn bạn, tớ luôn cố gắng trung thực nhất có thể."
    ]
    
    # 3. Mock LLM response JSON cho reflection
    reflection_json = {
        "insight": "Tôi nhận ra mình là một người bạn chân thành và luôn đề cao sự trung thực.",
        "value_updates": [
            {"name": "Sự Trung thực", "sentiment": 0.95, "type": "core", "reason": "User khen ngợi sự trung thực."},
            {"name": "Sự Giúp đỡ", "sentiment": 0.8, "type": "core", "reason": "Cảm thấy hạnh phúc khi giúp đỡ."}
        ]
    }
    mock_llm.generate_text.return_value = json.dumps(reflection_json)
    
    # 4. Mock memory methods
    engine.memory.add_memory = MagicMock()
    engine.memory.store = MagicMock() # Tránh ghi vào DB thật
    
    # 5. Chạy reflection
    print(f"\n[STEP] Đang chạy _identity_evolution_phase...")
    engine.memory_ops._identity_evolution_phase()
    
    # 6. Kiểm tra kết quả
    # Kiểm tra xem có thêm Memory CORE không
    added_mems = engine.memory.add_memory.call_args_list
    insight_found = False
    for call in added_mems:
        mem = call[0][0]
        if "Nhận thức Bản thể" in mem.content:
            insight_found = True
            print(f"  {Fore.GREEN}✅ SUCCESS: Đã thêm ký ức CORE về bản sắc.{Style.RESET_ALL}")
            break
    
    if not insight_found:
        print(f"  {Fore.RED}❌ FAILED: Không tìm thấy ký ức CORE mới.{Style.RESET_ALL}")

    # Kiểm tra ValueSystem
    honesty_val = engine.value_system.core_values.get("Sự Trung Thực")
    # Lưu ý: title() sẽ biến 'Sự Trung thực' thành 'Sự Trung Thực'
    if honesty_val and honesty_val > 0.9:
        print(f"  {Fore.GREEN}✅ SUCCESS: Value 'Sự Trung thực' đã được cập nhật lên {honesty_val:.2f}.{Style.RESET_ALL}")
    else:
        print(f"  {Fore.RED}❌ FAILED: ValueSystem không được cập nhật đúng.{Style.RESET_ALL}")
            
    print(f"\n{Fore.CYAN}=== KẾT THÚC KIỂM TRA C1 ==={Style.RESET_ALL}")

if __name__ == "__main__":
    test_reflection_evolution()
