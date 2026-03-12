import time
import sys
from unittest.mock import MagicMock, patch
import numpy as np

# Mock modules
sys.modules['core.world_graph'] = MagicMock()
sys.modules['core.local_perception'] = MagicMock()
sys.modules['core.tools'] = MagicMock()
sys.modules['components.reader'] = MagicMock()

from core.engine.cognitive_engine import CognitiveEngine
from core.memory import MemoryTrace
from colorama import Fore, Style

def test_brain_fog():
    print(f"{Fore.CYAN}--- KIỂM CHỨNG REFINED BRAIN FOG (B3) ---{Style.RESET_ALL}")
    
    # 1. Setup Engine với Mock
    mock_llm = MagicMock()
    mock_embedder = MagicMock()
    mock_embedder.encode.return_value = [0.1] * 1024
    
    engine = CognitiveEngine(llm=mock_llm, embedder=mock_embedder)
    
    # Tạo ký ức mẫu với nhiều chi tiết cụ thể
    sample_content = "Vào lúc 14:30 ngày 25/12/2025, Elon Musk đã mua 500 chiếc Tesla tại Texas."
    mock_memory = MemoryTrace(
        content=sample_content, 
        type="episodic",
        valence=0.5, 
        arousal=0.3, 
        importance=0.8,
        strength=1.0
    )
    
    # Giả lập search_memories trả về ký ức này
    engine.memory.search_memories = MagicMock(return_value=[(0.9, mock_memory)])
    
    # Kịch bản 1: Aura Tỉnh táo (Fatigue 0.0)
    print(f"\n[SCENARIO 1] Aura tỉnh táo (Fatigue 0.0)")
    engine.ego.fatigue = 0.0
    engine.ego.stress = 0.1
    
    recalled = engine.memory_ops.recall("Elon Musk")
    content_recalled = recalled[0].get_display_content()
    masked_content = engine.memory_ops._apply_fog_masking(content_recalled)
    
    print(f"  - Gốc: {sample_content}")
    print(f"  - Aura nhớ: {masked_content}")
    
    if "14:30" in masked_content and "Elon Musk" in masked_content:
        print(f"  {Fore.GREEN}✅ SUCCESS: Thông tin rõ ràng khi tỉnh táo.{Style.RESET_ALL}")
    else:
        print(f"  {Fore.RED}❌ FAILED: Bị che mờ nhầm khi tỉnh táo.{Style.RESET_ALL}")

    # Kịch bản 2: Aura Kiệt sức (Fatigue 0.95)
    print(f"\n[SCENARIO 2] Aura kiệt sức (Fatigue 0.95)")
    engine.ego.fatigue = 0.95
    engine.ego.stress = 0.8
    
    recalled_fog = engine.memory_ops.recall("Elon Musk")
    # Chúng ta test hàm Masking trực tiếp vì interaction controller dùng nó
    masked_fog = engine.memory_ops._apply_fog_masking(sample_content)
    
    print(f"  - Aura nhớ: {masked_fog}")
    
    # Kiểm tra các tag che mờ
    checks = {
        "thời gian": "[thời gian không rõ]" in masked_fog,
        "ngày tháng": "[ngày tháng bị nhòe]" in masked_fog,
        "số liệu": "[dữ liệu mờ nhạt]" in masked_fog,
        "tên riêng": "[tên ai đó?]" in masked_fog
    }
    
    all_passed = True
    for label, passed in checks.items():
        if passed:
            print(f"  {Fore.GREEN}✅ SUCCESS: Đã che mờ {label}.{Style.RESET_ALL}")
        else:
            print(f"  {Fore.RED}❌ FAILED: Không che mờ {label}.{Style.RESET_ALL}")
            all_passed = False

    if all_passed:
        print(f"\n{Fore.CYAN}=== KẾT THÚC KIỂM TRA B3 THÀNH CÔNG ==={Style.RESET_ALL}")
    else:
        print(f"\n{Fore.RED}=== KIỂM CHỨNG B3 THẤT BẠI ==={Style.RESET_ALL}")

if __name__ == "__main__":
    test_brain_fog()
