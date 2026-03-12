import json
import unittest
from unittest.mock import MagicMock, patch
import numpy as np
import sys

# Mock modules
sys.modules['core.world_graph'] = MagicMock()
sys.modules['core.value_system'] = MagicMock()
sys.modules['core.local_perception'] = MagicMock()
sys.modules['core.tools'] = MagicMock()
sys.modules['components.reader'] = MagicMock()

from core.engine.cognitive_engine import CognitiveEngine
from core.memory import MemoryTrace, MemoryType
from colorama import Fore, Style

def run_sprint_a_final_test():
    print(f"{Fore.CYAN}=== FINAL VERIFICATION: SPRINT A - SYSTEM INTEGRATION ==={Style.RESET_ALL}")
    
    # 1. Khởi tạo Engine với Mock
    mock_llm = MagicMock()
    mock_embedder = MagicMock()
    mock_embedder.encode.return_value = np.zeros(1024).tolist()
    
    engine = CognitiveEngine(llm=mock_llm, embedder=mock_embedder)
    
    # Giả lập LLM cho Semanticization
    mock_llm.generate_text.return_value = json.dumps([{
        "tags": ["test"], "reasoning": "Test reasoning", "conclusion": "Kết luận tổng quát"
    }])

    # 2. Thiết lập trạng thái ban đầu "Tệ hại"
    engine.ego.stress = 0.9
    engine.ego.fatigue = 0.8
    engine.ego.energy = 0.1
    engine.ego.atp_level = 0.1
    
    # Tạo 5 ký ức rác (yếu)
    for i in range(5):
        m = MemoryTrace(content=f"Ký ức rác {i}", type=MemoryType.EPISODIC, valence=0, arousal=0, importance=0.1)
        m.strength = 0.3
        engine.memory.add_memory(m)
        
    print(f"Trạng thái trước khi ngủ: Stress={engine.ego.stress:.2f}, Fatigue={engine.ego.fatigue:.2f}, Energy={engine.ego.energy:.2f}")
    print(f"Số lượng ký ức: {len(engine.memory.get_all())}")

    # 3. Thực thi Giấc ngủ (Sleep Cycle)
    print(f"\n{Fore.YELLOW}[ACTION] Aura đi ngủ...{Style.RESET_ALL}")
    engine.memory_ops.sleep()

    # 4. Kiểm chứng các cột mốc
    print(f"\n{Fore.CYAN}--- KẾT QUẢ KIỂM CHỨNG ---{Style.RESET_ALL}")
    
    # A. Sinh học
    if engine.ego.fatigue == 0 and engine.ego.energy == 1.0 and engine.ego.atp_level == 1.0:
        print(f"{Fore.GREEN}✅ BIOLOGICAL RECOVERY: Fatigue=0, Energy/ATP restored.{Style.RESET_ALL}")
    else:
        print(f"{Fore.RED}❌ BIOLOGICAL RECOVERY FAILED. Energy={engine.ego.energy}{Style.RESET_ALL}")

    # B. Trí nhớ (Semanticization)
    mems = engine.memory.get_all()
    has_semantic = any(m.type == MemoryType.SEMANTIC for m in mems)
    if has_semantic:
        print(f"{Fore.GREEN}✅ SEMANTICIZATION: Đã đúc kết được kiến thức mới từ rác.{Style.RESET_ALL}")
    else:
        print(f"{Fore.RED}❌ SEMANTICIZATION FAILED.{Style.RESET_ALL}")

    # C. Cắt tỉa (Pruning)
    has_trash = any("Ký ức rác" in m.content for m in mems)
    if not has_trash:
        print(f"{Fore.GREEN}✅ SYNAPTIC PRUNING: Các ký ức yếu đã bị xóa bỏ hoàn toàn.{Style.RESET_ALL}")
    else:
        print(f"{Fore.YELLOW}⚠️ SYNAPTIC PRUNING PARTIAL: Vẫn còn vài mẩu rác (có thể do strength chưa đủ thấp).{Style.RESET_ALL}")

    print(f"\n{Fore.GREEN}=== HOÀN THÀNH KIỂM CHỨNG SPRINT A ==={Style.RESET_ALL}")

if __name__ == "__main__":
    run_sprint_a_final_test()
