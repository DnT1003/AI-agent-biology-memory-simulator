import json
import unittest
from unittest.mock import MagicMock, patch
import numpy as np
import sys

# Mock các module nặng TRƯỚC khi import CognitiveEngine
sys.modules['core.world_graph'] = MagicMock()
sys.modules['core.value_system'] = MagicMock()
sys.modules['core.local_perception'] = MagicMock()
sys.modules['core.tools'] = MagicMock()
sys.modules['components.reader'] = MagicMock()

from core.engine.cognitive_engine import CognitiveEngine
from core.memory import MemoryTrace, MemoryType
from colorama import Fore, Style

def test_sleep_semanticization():
    print(f"{Fore.CYAN}--- KIỂM CHỨNG SLEEP & SEMANTICIZATION (A2) - SUPER MOCK MODE ---{Style.RESET_ALL}")
    
    # 1. Setup Engine với Mock LLM và Mock Embedder
    mock_llm = MagicMock()
    mock_embedder = MagicMock()
    mock_memory = MagicMock()
    
    # Mock Embedder trả về vector ngẫu nhiên
    mock_embedder.encode.return_value = np.zeros(1024).tolist()
    
    # Mock Memory Manager
    mems_storage = []
    def add_mem(m): mems_storage.append(m)
    def get_all(): return mems_storage
    mock_memory.add_memory.side_effect = add_mem
    mock_memory.get_all.side_effect = get_all
    
    # Khởi tạo engine với các mock
    engine = CognitiveEngine(llm=mock_llm, embedder=mock_embedder, memory=mock_memory)
    ops = engine.memory_ops
    
    # Giả lập kết quả từ LLM cho việc gộp ký ức
    mock_insight = [
        {
            "tags": ["social", "preference"],
            "reasoning": "User thường xuyên nhắc đến việc thích uống cà phê vào buổi sáng và không thích trà.",
            "conclusion": "Người dùng là một tín đồ của cà phê sáng."
        }
    ]
    mock_llm.generate_text.return_value = json.dumps(mock_insight)

    # 2. Tạo các ký ức yếu ( Episodic, strength < 0.4)
    m1 = MemoryTrace(content="User nói thích uống cà phê", type=MemoryType.EPISODIC, valence=0.5, arousal=0.2, importance=0.3)
    m1.strength = 0.3
    m2 = MemoryTrace(content="Hôm nay User lại uống cà phê đen", type=MemoryType.EPISODIC, valence=0.5, arousal=0.1, importance=0.2)
    m2.strength = 0.2
    m3 = MemoryTrace(content="User chê trà đắng", type=MemoryType.EPISODIC, valence=-0.1, arousal=0.1, importance=0.2)
    m3.strength = 0.2
    
    # Chỉ định các ID cho dễ theo dõi
    m1.id = "m1"
    m2.id = "m2"
    m3.id = "m3"
    
    engine.memory.add_memory(m1)
    engine.memory.add_memory(m2)
    engine.memory.add_memory(m3)
    
    print(f"Số lượng ký ức ban đầu: {len(mems_storage)}")

    # 3. Chạy pha Dream Consolidation
    print("\n[STEP] Chạy _dream_consolidation_phase...")
    ops._dream_consolidation_phase()
    
    # 4. Kiểm chứng kết quả
    mems = engine.memory.get_all()
    print(f"Số lượng ký ức sau khi gộp: {len(mems)}")
    
    # Kiểm tra xem có Semantic memory mới không
    # Vì logic cũ delete m1, m2, m3 -> mems chỉ còn Semantic + Core Belief
    semantic_mems = [m for m in mems if m.type == MemoryType.SEMANTIC]
    if semantic_mems:
        print(f"{Fore.GREEN}✅ Đã tạo ký ức Semantic mới: {semantic_mems[0].content}{Style.RESET_ALL}")
    else:
        print(f"{Fore.RED}❌ Không tìm thấy ký ức Semantic mới.{Style.RESET_ALL}")

    # Kiểm tra Pruning
    # Ops gọi engine.memory.store.remove(m_id) trực tiếp
    # Cần mock store để check
    if engine.memory.store.remove.called:
        print(f"{Fore.GREEN}✅ Pruning hoạt động: Hàm remove() ở Store đã được gọi.{Style.RESET_ALL}")
    else:
        print(f"{Fore.RED}❌ Pruning KHÔNG hoạt động.{Style.RESET_ALL}")

if __name__ == "__main__":
    test_sleep_semanticization()
