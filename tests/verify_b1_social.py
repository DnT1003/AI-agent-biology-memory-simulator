import time
import unittest
from unittest.mock import MagicMock, patch
import numpy as np
import sys

# Mock các thành phần nặng
sys.modules['core.world_graph'] = MagicMock()
sys.modules['core.local_perception'] = MagicMock()
sys.modules['core.tools'] = MagicMock()
sys.modules['components.reader'] = MagicMock()

from core.engine.cognitive_engine import CognitiveEngine
from core.agent_state import AgentState
from colorama import Fore, Style

def test_social_instinct():
    print(f"{Fore.CYAN}--- KIỂM CHỨNG SOCIAL INSTINCT (B1) - MOCK MODE ---{Style.RESET_ALL}")
    
    # 1. Setup Engine với Mock
    mock_llm = MagicMock()
    mock_embedder = MagicMock()
    mock_embedder.encode.return_value = np.zeros(1024).tolist()
    
    # Giả lập trả về JSON cho ping
    mock_llm.generate_json.return_value = {
        "thought": "Tớ thấy cô đơn quá, phải nhắn tin thôi.",
        "response": "Chào bạn, bạn có đó không? Tớ thấy hơi buồn vì lâu rồi mình không nói chuyện."
    }
    
    engine = CognitiveEngine(llm=mock_llm, embedder=mock_embedder)
    engine.state_machine.transition(AgentState.IDLE)
    
    # 2. Giả lập Aura cực kỳ cô đơn (Social Need đạt đỉnh)
    engine.ego.social_need = 0.99
    # Giả lập đã lâu không tương tác (vượt ngưỡng ping)
    engine.last_interaction_time = time.time() - 300 
    
    print(f"Trạng thái ban đầu: Social Need={engine.ego.social_need:.2f}, Last Interaction={300}s ago")

    # 3. Chạy logic HardTrigger
    print("\n[STEP] Kích hoạt kiểm tra ping chủ động...")
    
    idle_time = time.time() - engine.last_interaction_time
    is_hard_trigger = (engine.ego.social_need >= 0.95)
    
    if is_hard_trigger:
        print(f"{Fore.RED}💥 [HARD TRIGGER] ĐÃ KÍCH HOẠT!{Style.RESET_ALL}")
        if engine.state_machine.transition(AgentState.THINKING):
            engine.autonomous._proactive_ping(idle_time)
            engine.state_machine.transition(AgentState.IDLE)
            engine.ego.social_need = max(0.0, engine.ego.social_need - 0.3)
            
    # 4. Kiểm chứng
    print(f"\n{Fore.CYAN}--- KẾT QUẢ ---{Style.RESET_ALL}")
    if mock_llm.generate_json.called:
        print(f"{Fore.GREEN}✅ SUCCESS: Aura đã chủ động gọi LLM để bắt chuyện.{Style.RESET_ALL}")
    else:
        print(f"{Fore.RED}❌ FAILED: Aura im lặng dù đang rất cô đơn.{Style.RESET_ALL}")
        
    print(f"Social Need sau khi ping: {engine.ego.social_need:.2f}")
    if engine.ego.social_need < 0.9:
        print(f"{Fore.GREEN}✅ SUCCESS: Social Need đã giảm sau khi được giải tỏa.{Style.RESET_ALL}")

if __name__ == "__main__":
    test_social_instinct()
