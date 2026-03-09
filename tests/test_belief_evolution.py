import os
import sys
import json
from colorama import Fore, Style

# Gia lap moi truong
sys.path.append(os.getcwd())

from core.engine.memory_ops import MemoryOperationsController
from core.memory import MemoryTrace, MemoryType
from unittest.mock import MagicMock

def test_belief_evolution():
    print(f"{Fore.CYAN}🧪 [TEST]: Bat dau thu nghiem chuc nang Cap nhat Niem tin Đe quy (Feature 2)...{Style.RESET_ALL}")
    
    # Mock Engine
    engine = MagicMock()
    engine._memory_lock = MagicMock()
    engine.short_term_buffer = ["Fixing conflicts"]
    
    # Tao tap niem tin mau thuan
    b1 = MemoryTrace(id="b1", content="Niềm tin cốt lõi (Belief): Luôn luôn tin tưởng mọi người vô điều kiện.", type=MemoryType.CORE, valence=0.5, arousal=0.5, importance=1.0)
    b2 = MemoryTrace(id="b2", content="Niềm tin cốt lõi (Belief): Thế giới này đầy rẫy sự lừa lọc, không được tin ai.", type=MemoryType.CORE, valence=-0.5, arousal=0.8, importance=1.0)
    
    engine.memory.get_all.return_value = [b1, b2]
    
    # Mock LLM
    engine.llm = MagicMock()
    resolution_json = {
        "analysis": "Phát hiện hai niềm tin đối lập cực đoan về sự tin tưởng.",
        "resolutions": [
            {
                "type": "MERGE",
                "indices": [0, 1],
                "new_content": "Sự tin tưởng là quý giá nhưng cần đi kèm với sự quan sát và thấu hiểu, không nên mù quáng cũng không nên cực đoan.",
                "reason": "Hợp nhất hai thái cực thành một thế giới quan thực tế hơn."
            }
        ]
    }
    engine.llm.generate_text.return_value = json.dumps(resolution_json)
    
    # Init Controller
    controller = MemoryOperationsController(engine)
    
    # Execute Phase
    print(f"{Fore.YELLOW}Aura dang rà soát và giải quyết mâu thuẫn nhận thức...{Style.RESET_ALL}")
    controller._belief_evolution_phase()
    
    # Verify calls
    # 1. Da goi lenh xoa b1 va b2
    delete_ids = [call.kwargs['record_id'] if 'record_id' in call.kwargs else call.args[0] for call in engine.memory.store.remove.call_args_list]
    print(f"\n{Fore.WHITE}Ket qua giai quyet:{Style.RESET_ALL}")
    
    if "b1" in delete_ids and "b2" in delete_ids:
        print(f"{Fore.GREEN}✅ SUCCESS: Da xoa bo cac niem tin mau thuan cu (b1, b2).{Style.RESET_ALL}")
    else:
        print(f"{Fore.RED}❌ FAILURE: Khong xoa dung cac niem tin cu. IDs da xoa: {delete_ids}{Style.RESET_ALL}")

    # 2. Da nạp niềm tin mới
    added_mems = [call.args[0].content for call in engine.memory.add_memory.call_args_list]
    if any("Sự tin tưởng là quý giá" in txt for txt in added_mems):
        print(f"{Fore.GREEN}✅ SUCCESS: Da nap niem tin moi sau khi hop nhat.{Style.RESET_ALL}")
    else:
        print(f"{Fore.RED}❌ FAILURE: Khong tim thay niem tin moi duoc nap. Content: {added_mems}{Style.RESET_ALL}")

if __name__ == "__main__":
    test_belief_evolution()
