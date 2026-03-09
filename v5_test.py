import time
import random
from core.self_model import SelfModel
from core.engine.sensory_preprocessor import SensoryPreprocessor
from core.engine.bio_controller import BioController

def test_bio_stochasticity():
    print("--- TESTING BIO-STOCHASTICITY ---")
    ego = SelfModel()
    
    # Test multiple updates to see jitter
    fatigues = []
    for _ in range(10):
        # Giả lập trôi qua 1 giờ làm việc căng thẳng
        ego.stress = 0.8
        ego.apply_biological_decay(3600, 0)
        fatigues.append(round(ego.fatigue, 4))
    
    print(f"Fatigue progression (with jitter): {fatigues}")
    
    # Kiểm tra tính không đồng nhất (đảm bảo không tăng tuyến tính tuyệt đối)
    diffs = [fatigues[i] - fatigues[i-1] for i in range(1, len(fatigues))]
    if len(set(diffs)) > 1:
        print("✅ SUCCESS: Stochastic Jitter detected in Fatigue.")
    else:
        print("❌ FAILURE: Fatigue increased linearly (no jitter).")

def test_sensory_vector():
    print("\n--- TESTING SENSORY VECTOR ---")
    sp = SensoryPreprocessor()
    
    inputs = [
        "DO IT NOW!!!",
        "Hmm, maybe we can try that later...",
        "I hate this, it's so wrong and bad!",
        "Wow, you are so amazing and lovely!"
    ]
    
    for text in inputs:
        eval = sp.evaluate_input(text)
        vec = eval['vector']
        print(f"Input: '{text}'")
        print(f"   -> Valence: {vec['valence']}, Arousal: {vec['arousal']}, Urgency: {vec['urgency']}")

if __name__ == "__main__":
    test_bio_stochasticity()
    test_sensory_vector()
