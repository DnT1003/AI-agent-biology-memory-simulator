import os
import sys
import shutil
import time
import json
from colorama import Fore, Style

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Force UTF-8 output
if sys.stdout.encoding != 'utf-8':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from core.engine.cognitive_engine import CognitiveEngine
from core.memory import MemoryTrace, MemoryType
from components.llm import LLM
from components.embedder import Embedder
from config import Config

class MockLLM:
    def __init__(self):
        self.responses = {
            "YES": "YES",
            "EVOLVE": '{"action": "EVOLVE", "reasoning": "User has shown consistency.", "new_belief": "Sự kiên nhẫn dẫn đến thành quả."}',
            "SOFTEN": '{"action": "SOFTEN", "reasoning": "Maybe I should be less strict.", "new_belief": ""}',
            "REJECT": '{"action": "REJECT", "reasoning": "This sounds fake.", "new_belief": ""}'
        }
        self.default_response = "NO"

    def generate_text(self, prompt, **kwargs):
        if "MÂU THUẪN HOÀN TOÀN" in prompt:
            if "sai sự thật" in prompt or "mâu thuẫn" in prompt:
                return "YES"
            return "NO"
        if "Nhiệm vụ: Phân tích" in prompt:
            return self.responses["EVOLVE"]
        
        if "Semanticization" in prompt or "Dream" in prompt:
            return '{"conclusion": "Thành quả", "reasoning": "Test", "tags": ["test"]}'
            
        return self.default_response

class MockEmbedder:
    def encode(self, text):
        import numpy as np
        # Trả về vector giống hệt nhau cho tất cả mọi thứ để cosine similarity luôn = 1.0!
        return np.ones(32, dtype=np.float32)

def test_resilience_and_growth():
    print(f"\n{Fore.CYAN}🛡️  PHASE 20 TEST — Resilience & Growth{Style.RESET_ALL}")
    
    # Setup
    db_path = os.path.abspath("outputs/test_resilience_db")
    if os.path.exists(db_path):
        import shutil
        try:
            shutil.rmtree(db_path)
            time.sleep(1) # Chờ OS release file handle
        except:
            pass
    os.makedirs(db_path, exist_ok=True)
    
    # Override Config
    Config.CHROMA_DB_PATH = db_path
    Config.OUTPUT_DIR = "outputs"
    
    mock_llm = MockLLM()
    mock_embedder = MockEmbedder()
    engine = CognitiveEngine(llm=mock_llm, embedder=mock_embedder)
    
    # 1. Test Resilience accumulation through healing
    print(f"\n{Fore.YELLOW}1. Kiểm tra tích lũy Resilience qua Healing...{Style.RESET_ALL}")
    engine.ego.resilience = 0.0
    engine.ego.current_intimacy = 0.9 # High intimacy for healing
    
    # Add a trauma
    trauma = MemoryTrace(
        content="User mắng tôi là đống rác.",
        type=MemoryType.EPISODIC,
        valence=-0.8, arousal=0.8, importance=1.0, is_flashbulb=True
    )
    engine.memory.add_memory(trauma)
    
    mems = engine.memory.get_all()
    print(f"   Số ký ức trong DB: {len(mems)}")
    for m in mems:
        print(f"     - {m.content[:30]}... (is_flashbulb={m.is_flashbulb}, valence={m.valence})")
    
    print(f"   Resilience ban đầu: {engine.ego.resilience:.4f}")
    
    # Simulate 10 days of sleep/healing
    for i in range(10):
        engine.memory_ops.sleep()
    
    print(f"   Resilience sau 10 lượt healing: {engine.ego.resilience:.4f}")
    if engine.ego.resilience > 0:
        print(f"   {Fore.GREEN}OK: Resilience đã tăng theo quá trình chữa lành.{Style.RESET_ALL}")
    else:
        print(f"   {Fore.RED}FAIL: Resilience không tăng.{Style.RESET_ALL}")
        return

    # 2. Test Resilience Buffer in update_state
    print(f"\n{Fore.YELLOW}2. Kiểm tra Resilience Buffer giảm shock...{Style.RESET_ALL}")
    engine.ego.mood = 0.0
    engine.ego.resilience = 0.0
    engine.ego.update_state({"valence": -1.0, "arousal": 1.0})
    mood_drop_no_res = abs(engine.ego.mood)
    print(f"   Mood drop (Resilience=0.0): {mood_drop_no_res:.4f}")
    
    engine.ego.mood = 0.0
    engine.ego.resilience = 1.0
    engine.ego.update_state({"valence": -1.0, "arousal": 1.0})
    mood_drop_with_res = abs(engine.ego.mood)
    print(f"   Mood drop (Resilience=1.0): {mood_drop_with_res:.4f}")
    
    if mood_drop_with_res < mood_drop_no_res:
        reduction = (1 - mood_drop_with_res/mood_drop_no_res) * 100
        print(f"   {Fore.GREEN}OK: Resilience đã giảm {reduction:.1f}% tác động tiêu cực.{Style.RESET_ALL}")
    else:
        print(f"   {Fore.RED}FAIL: Resilience không có tác dụng cản phá.{Style.RESET_ALL}")
        return

    # 3. Test Cognitive Reappraisal (Belief Evolution)
    print(f"\n{Fore.YELLOW}3. Kiểm tra Cognitive Reappraisal & Belief Evolution...{Style.RESET_ALL}")
    # Clear memory for fresh test
    engine.memory.store.clear_all()
    
    # Add a core belief
    engine.memory.add_memory(MemoryTrace(
        content="Niềm tin cốt lõi (Belief): User luôn luôn đúng.",
        type=MemoryType.CORE,
        valence=0.5, arousal=0.1, importance=1.0, is_flashbulb=True
    ))
    
    # Input contradicting information
    contradiction = "User đã nói sai sự thật."
    perception = {"valence": -0.5, "arousal": 0.8, "importance": 0.8}
    
    print(f"   Input mâu thuẫn: '{contradiction}'")
    engine.memory_ops.update_or_add_memory(contradiction, perception)
    
    # Check if tagged
    mems = engine.memory.get_all()
    reeval_mems = []
    for m in mems:
        if "[ToReevaluate]" in m.content or any("[ToReevaluate]" in ov for ov in m.overlays):
            reeval_mems.append(m)
            
    if len(reeval_mems) > 0:
         print(f"   {Fore.GREEN}OK: Ký ức được gắn thẻ [ToReevaluate].{Style.RESET_ALL}")
    else:
         print(f"   {Fore.RED}FAIL: Ký ức không được gắn thẻ.{Style.RESET_ALL}")
         return
    
    # Sleep to trigger reappraisal
    print(f"   Aura đang ngủ và chiêm nghiệm về mâu thuẫn...")
    engine.memory_ops.sleep()
    
    # Check if new belief added
    mems_after = engine.memory.get_all()
    evolution_found = any("Sự kiên nhẫn dẫn đến thành quả." in m.content for m in mems_after)
    
    if evolution_found:
        print(f"   {Fore.GREEN}OK: [BELIEF EVOLUTION] thành công: Đã học được niềm tin mới.{Style.RESET_ALL}")
    else:
        print(f"   {Fore.RED}FAIL: Không tìm thấy niềm tin mới trong DB.{Style.RESET_ALL}")
        # print("Mems after:", [m.content for m in mems_after])
        return

    print(f"\n{Fore.GREEN}✅ TẤT CẢ CÁC BÀI KIỂM TRA ĐÃ VƯỢT QUA!{Style.RESET_ALL}")

if __name__ == "__main__":
    test_resilience_and_growth()
