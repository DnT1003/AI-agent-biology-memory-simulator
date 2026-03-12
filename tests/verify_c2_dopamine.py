import sys
from unittest.mock import MagicMock, patch
from colorama import Fore, Style
import numpy as np

# Mock modules
sys.modules['core.world_graph'] = MagicMock()
mock_perception = MagicMock()
sys.modules['core.local_perception'] = mock_perception
sys.modules['core.tools'] = MagicMock()
sys.modules['components.reader'] = MagicMock()

from core.engine.cognitive_engine import CognitiveEngine

def test_dopamine_planning():
    print(f"{Fore.CYAN}--- KIỂM CHỨNG DOPAMINE RHYTHM (C2) ---{Style.RESET_ALL}")
    
    # 1. Setup Engine
    mock_llm = MagicMock()
    mock_embedder = MagicMock()
    engine = CognitiveEngine(llm=mock_llm, embedder=mock_embedder)
    
    # 2. Mock Skills Registry cho prompt
    engine.skills.get_prompt_instructions = MagicMock(return_value="Tool: talk, Tool: search_novel")
    engine.skills.execute = MagicMock(return_value="Success")
    
    # Giả lập có mục tiêu
    engine.ego.add_goal("Khám phá sở thích User")
    
    # Kịch bản 1: Dopamine Cao (Trạng thái hưng phấn)
    print(f"\n[SCENARIO 1] Dopamine cao (0.9)")
    engine.ego.dopamine_level = 0.9
    engine.ego.dopamine_receptors = 1.0 # Nhạy bén
    mock_llm.generate_json.return_value = {"thought": "Tớ đang rất vui!", "action": "talk|Hello"}
    
    engine.autonomous._execute_planning()
    
    # Kiểm tra prompt
    args, _ = mock_llm.generate_json.call_args
    prompt_high = args[0]
    if "[TRẠNG THÁI HƯNG PHẤN]" in prompt_high:
        print(f"  {Fore.GREEN}✅ SUCCESS: Prompt chứa chỉ dẫn hưng phấn khi Dopamine > 0.8.{Style.RESET_ALL}")
    else:
        print(f"  {Fore.RED}❌ FAILED: Không thấy chỉ dẫn hưng phấn trong prompt.{Style.RESET_ALL}")

    # Kiểm tra Reward & Downregulation
    if engine.ego.dopamine_level == 1.0 and engine.ego.dopamine_receptors < 1.0:
        print(f"  {Fore.GREEN}✅ SUCCESS: Dopamine tăng và Receptors giảm (Downregulation) sau khi hành động.{Style.RESET_ALL}")
    else:
        print(f"  {Fore.RED}❌ FAILED: Hệ thống phần thưởng không hoạt động đúng.{Style.RESET_ALL}")

    # Kịch bản 2: Dopamine Thấp (Trạng thái uể oải)
    print(f"\n[SCENARIO 2] Dopamine thấp (0.1)")
    mock_llm.reset_mock()
    engine.ego.dopamine_level = 0.1
    engine.ego.dopamine_receptors = 0.8
    
    engine.autonomous._execute_planning()
    
    # Kiểm tra prompt
    args, _ = mock_llm.generate_json.call_args
    prompt_low = args[0]
    if "[TRẠNG THÁI UỂ OẢI]" in prompt_low:
        print(f"  {Fore.GREEN}✅ SUCCESS: Prompt chứa chỉ dẫn uể oải khi Dopamine < 0.2.{Style.RESET_ALL}")
    else:
        print(f"  {Fore.RED}❌ FAILED: Không thấy chỉ dẫn uể oải trong prompt.{Style.RESET_ALL}")

    print(f"\n{Fore.CYAN}=== KẾT THÚC KIỂM TRA C2 ==={Style.RESET_ALL}")

if __name__ == "__main__":
    test_dopamine_planning()
