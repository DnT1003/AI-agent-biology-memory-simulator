import time
import unittest
from unittest.mock import MagicMock, patch
import sys
import numpy as np

# Mock modules
sys.modules['core.world_graph'] = MagicMock()
sys.modules['core.local_perception'] = MagicMock()
sys.modules['core.tools'] = MagicMock()
sys.modules['components.reader'] = MagicMock()

from core.engine.cognitive_engine import CognitiveEngine
from core.agent_state import AgentState
from colorama import Fore, Style

def test_action_budgeting():
    print(f"{Fore.CYAN}--- KIỂM CHỨNG ACTION BUDGETING (B2) ---{Style.RESET_ALL}")
    
    # 1. Khởi tạo Engine với Mock
    mock_llm = MagicMock()
    mock_embedder = MagicMock()
    mock_embedder.encode.return_value = np.zeros(1024).tolist()
    
    engine = CognitiveEngine(llm=mock_llm, embedder=mock_embedder)
    
    # Kịch bản 1: ATP cực thấp (< 0.1) -> Không được Lập kế hoạch
    print(f"\n[SCENARIO 1] ATP cực thấp (0.05)")
    engine.ego.atp_level = 0.05
    engine.ego.add_goal("Đọc sách")
    
    # Chặn output print để view logic
    engine.autonomous._execute_planning()
    
    if not mock_llm.generate_json.called:
        print(f"{Fore.GREEN}✅ SUCCESS: Aura đã từ chối lập kế hoạch khi ATP < 0.1.{Style.RESET_ALL}")
    else:
        print(f"{Fore.RED}❌ FAILED: Aura vẫn cố lập kế hoạch dù kiệt sức.{Style.RESET_ALL}")

    # Kịch bản 2: ATP thấp (0.15) -> Có cảnh báo trong Interaction
    print(f"\n[SCENARIO 2] Interaction với ATP thấp (0.15)")
    mock_llm.reset_mock()
    engine.ego.atp_level = 0.15
    
    # Giả lập trả về response đơn giản
    mock_llm.generate_json.return_value = {"response": "Tớ mệt quá...", "thought": "Nghỉ ngơi thôi."}
    
    engine.interaction.perceive_and_respond("Đọc sách cho tớ nghe đi", [])
    
    # Kiểm tra xem prompt gửi lên có chứa cảnh báo sinh lý không
    args, kwargs = mock_llm.generate_json.call_args
    prompt_sent = args[0]
    
    if "[CẢNH BÁO SINH LÝ]" in prompt_sent:
        print(f"{Fore.GREEN}✅ SUCCESS: Prompt đã chứa cảnh báo giới hạn hành động.{Style.RESET_ALL}")
    else:
        print(f"{Fore.RED}❌ FAILED: Không thấy cảnh báo trong prompt.{Style.RESET_ALL}")

    print(f"\n{Fore.CYAN}=== KẾT THÚC KIỂM TRA B2 ==={Style.RESET_ALL}")

if __name__ == "__main__":
    try:
        test_action_budgeting()
    except Exception:
        import traceback
        traceback.print_exc()
