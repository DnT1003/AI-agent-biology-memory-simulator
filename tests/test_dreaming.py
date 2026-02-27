import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.engine.cognitive_engine import CognitiveEngine
from core.memory import MemoryTrace

def test_dreaming():
    print("=== TEST ABSTRACT DREAMING & HALLUCINATIONS ===")
    
    engine = CognitiveEngine()
    
    # Inject fake episodic memories
    mems = [
        MemoryTrace("Tôi nhìn thấy con chó nhà hàng xóm màu vàng đang sủa.", type='episodic', valence=0.0, arousal=0.5, importance=0.5),
        MemoryTrace("Một người kể tôi nghe câu chuyện về ma sói đêm rằm.", type='episodic', valence=-0.3, arousal=0.5, importance=0.6),
        MemoryTrace("Hôm nay tôi ăn bánh cuốn, nước mắm hơi mặn.", type='episodic', valence=0.0, arousal=0.3, importance=0.4),
        MemoryTrace("Có trận động đất nhẹ làm rung rinh mặt bàn.", type='episodic', valence=-0.2, arousal=0.6, importance=0.7),
        MemoryTrace("Tôi đọc sách lúc nửa đêm về công nghệ AI.", type='episodic', valence=0.0, arousal=0.5, importance=0.5),
    ]
    for m in mems:
        engine.memory.add_memory(m)
        
    print(f"Added {len(mems)} episodic memories.")
    print("Forcing sleep cycles to capture hallucinations...")
    
    # Force hallucination probability to 1.0 for testing purposes by monkeypatching
    import random
    original_random = random.random
    random.random = lambda: 0.1 # This will force random.random() < 0.3 to be True
    
    try:
        engine.sleep()
    finally:
        random.random = original_random
        
    print("\n[Resulting Beliefs and Semantic Memories]:")
    all_mems = engine.memory.get_all()
    hallucination_found = any("ẢO GIÁC" in str(getattr(m, 'content', '')) for m in all_mems)
    
    for m in all_mems:
        if m.type == 'semantic':
            print(f"-> {m.content} (Valence: {m.valence})")
            
    if hallucination_found:
        print("\n✅ Hallucination logic works!")
    else:
        print("\n❌ Hallucination was not generated or saved properly.")

if __name__ == "__main__":
    test_dreaming()
