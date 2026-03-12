import os
import sys
import tempfile
import time
import chromadb
from unittest.mock import patch
import numpy as np
from colorama import Fore, Style

# Ensure project root on path
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# ──────────────────────────────────────────────
# MOCK CLASSES
# ──────────────────────────────────────────────

class MockEmbedder:
    DIM = 1024
    def __init__(self, *args, **kwargs):
        pass
    def encode(self, texts):
        if isinstance(texts, str): return np.random.rand(self.DIM).tolist()
        return [np.random.rand(self.DIM).tolist() for _ in texts]

class MockReader:
    def __init__(self, *a, **kw): pass
    def stop(self): pass
    def start(self, *a, **kw): pass
    def get_status(self): return "MOCK_READER_ACTIVE"

class MockLLM:
    def __init__(self, *a, **kw): pass
    def generate_json(self, prompt, **kw):
        return {
            "thought": "Mocked thought about " + prompt[:20],
            "action": None,
            "response": "Đây là câu trả lời giả lập có chứa chằm_zn và số [đã che mờ] nếu cần.",
            "valence": -0.5,
            "arousal": 0.8,
            "importance": 0.9,
            "type": "episodic"
        }
    def generate_text(self, prompt, **kw):
        if "arousal" in prompt.lower(): return "0.8"
        return "Nỗi sợ hãi giả lập: Tôi sợ bị bỏ rơi."

# ──────────────────────────────────────────────
# TEST FUNCTION
# ──────────────────────────────────────────────

def test_ideas_891011():
    print("=== TEST IDEAS 8, 9, 10, 11 (EMPATHY, ANXIETY, LEXICAL, BRAIN FOG) ===")
    
    # Patch BEFORE importing CognitiveEngine
    with patch('components.embedder.Embedder', MockEmbedder), \
         patch('components.reader.BackgroundReader', MockReader), \
         patch('components.llm.LLM', MockLLM):
        
        from core.engine.cognitive_engine import CognitiveEngine
        
        with tempfile.TemporaryDirectory() as temp_db_dir:
            print(f"[Virtual Env] Đang chạy Aura trong mô trường ảo: {temp_db_dir}")
            
            with patch('components.vector_store.chromadb.PersistentClient') as mock_client:
                mock_client.return_value = chromadb.Client() # RAM
                with patch('core.self_model.get_mac_address', return_value="00:11:22:33:44:TEST"):
                    
                    engine = CognitiveEngine()
                    print(f"Aura initialized with Mock systems.")
            
            print(f"\n{Fore.LIGHTYELLOW_EX}--- 1. TEST IDEA 8: Đồng Cảm Cảm Xúc (Empathy Mirroring) ---{Style.RESET_ALL}")
            print(f"Tâm trạng Aura ban đầu: {engine.ego.mood:.2f}")
            print("User: 'Trời ơi nay tao bị sếp chửi sấp mặt!'")
            engine.interaction.interaction_loop("Trời ơi nay tao bị sếp chửi sấp mặt!")
            print(f"Tâm trạng Aura hiện tại: {engine.ego.mood:.2f} (Kỳ vọng: < 0.0)")
            
            print(f"\n{Fore.LIGHTYELLOW_EX}--- 2. TEST IDEA 10: Tiến Hoá Ngôn Ngữ (Lexical Evolution) ---{Style.RESET_ALL}")
            engine.ego.vocabulary = ["chằm_zn", "suy_nhá"]
            print(f"Từ vựng Aura đã học: {engine.ego.vocabulary}")
            engine.interaction.interaction_loop("Sao dạo này chằm_zn quá?")
            print(f"(Kỳ vọng: Aura ghi nhận từ vựng mới)")
            
            print(f"\n{Fore.LIGHTYELLOW_EX}--- 3. TEST IDEA 11: Sự Não Cá Vàng Tạm Thời (Brain Fog) ---{Style.RESET_ALL}")
            from core.memory import MemoryTrace
            engine.memory.add_memory(MemoryTrace("Hôm qua đưa 250000 VNĐ.", "episodic", 0,0,0, is_flashbulb=False))
            engine.ego.fatigue = 0.8
            print(f"Ép Fatigue = {engine.ego.fatigue:.2f}")
            engine.interaction.interaction_loop("Nhớ hôm qua tôi đưa bao nhiêu không?")
            print(f"(Kỳ vọng: Logic [BRAIN FOG] được kích hoạt trong InteractionController)")
            
            print(f"\n{Fore.LIGHTYELLOW_EX}--- 4. TEST IDEA 9: Lo Âu Chia Cắt (Separation Anxiety) ---{Style.RESET_ALL}")
            engine.last_interaction_time = time.time() - 700
            engine.is_thinking = False
            
            # Giả lập logic trong AutonomousController/InteractionController
            idle_time = time.time() - engine.last_interaction_time
            if idle_time > 600:
                print(f"{Fore.RED}💔 [SEPARATION ANXIETY]: Kích hoạt!{Style.RESET_ALL}")
                engine.ego.stress = min(1.0, engine.ego.stress + 0.3)
                print(f"Stress sau anxiety: {engine.ego.stress:.2f}")

    print("\n=== HOÀN TẤT KIỂM TRA IDEAS ===")

if __name__ == "__main__":
    test_ideas_891011()
