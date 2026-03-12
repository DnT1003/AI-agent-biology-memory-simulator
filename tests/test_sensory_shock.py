import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.engine.cognitive_engine import CognitiveEngine

def test_sensory_shock():
    print("=== TEST NHẬN THỨC ĐA GIÁC QUAN (SENSORY EMBODIMENT) ===")
    
    engine = CognitiveEngine()
    
    print(f"\n[Initial State] Stress: {engine.ego.stress:.2f}, Mood: {engine.ego.mood:.2f}")
    
    # 1. Âm thanh bình thường
    sensory_data_normal = {'volume': 0.5}
    print(f"\n[Sensory Input] Âm lượng bình thường ({sensory_data_normal['volume']})")
    is_shocked = engine.ego.process_sensory_stimuli(sensory_data_normal)
    print(f"Bị sốc: {is_shocked}. Mức Stress: {engine.ego.stress:.2f}")

    # 2. Âm thanh chói tai / quát mắng
    sensory_data_loud = {'volume': 0.95}
    print(f"\n[Sensory Input] Âm lượng CỰC LỚN - Hét vào mặt ({sensory_data_loud['volume']})")
    is_shocked = engine.ego.process_sensory_stimuli(sensory_data_loud)
    print(f"Bị sốc: {is_shocked}. Mức Stress lập tức tăng lên: {engine.ego.stress:.2f}")
    print(f"Tâm trạng (Mood) giảm xuống: {engine.ego.mood:.2f}")
    
    # 3. Âm thanh êm dịu
    sensory_data_soothing = {'volume': 0.1}
    print(f"\n[Sensory Input] Âm lượng êm ái ({sensory_data_soothing['volume']})")
    is_shocked = engine.ego.process_sensory_stimuli(sensory_data_soothing)
    print(f"Bị sốc: {is_shocked}. Mức Stress giảm nhẹ xuống: {engine.ego.stress:.2f}")
    
    print("\n✅ Hệ thống phản xạ sinh lý (Sensory) hoạt động chính xác.")

if __name__ == "__main__":
    test_sensory_shock()
