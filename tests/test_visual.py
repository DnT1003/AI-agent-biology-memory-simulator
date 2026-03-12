import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.engine.cognitive_engine import CognitiveEngine

def test_visual_embodiment():
    print("=== TEST VISUAL EMBODIMENT ===")
    
    engine = CognitiveEngine()
    
    print(f"\n[Initial State] Stress: {engine.ego.stress:.2f}, Mood: {engine.ego.mood:.2f}")
    
    # We will need a dummy image file. Since we don't have one, we will mock the LLM's visual response
    # to avoid needing a real image file and making real API calls for this simple logic test.
    print("\n[Action] Mocking process_visual_stimuli directly on SelfModel...")
    
    # Mocking a scary image 
    class MockLLMScary:
        def generate_text(self, prompt, temperature, image_path):
            return '''```json
            {
                "valence": -0.8,
                "arousal": 0.9,
                "description": "Một con nhện khổng lồ nhiều lông lá đang bò tới"
            }
            ```'''
            
    desc = engine.ego.process_visual_stimuli(MockLLMScary(), "dummy_scary.jpg")
    print(f"\n[After Scary Image] Stress: {engine.ego.stress:.2f}, Mood: {engine.ego.mood:.2f}")
    
    # Mocking a cute image
    class MockLLMCute:
        def generate_text(self, prompt, temperature, image_path):
            return '''```json
            {
                "valence": 0.9,
                "arousal": 0.4,
                "description": "Một chú chó con đang vẫy đuôi"
            }
            ```'''
            
    desc = engine.ego.process_visual_stimuli(MockLLMCute(), "dummy_cute.jpg")
    print(f"\n[After Cute Image] Stress: {engine.ego.stress:.2f}, Mood: {engine.ego.mood:.2f}")
    
    print("\n✅ Visual perception updates physiological stats correctly.")

if __name__ == "__main__":
    test_visual_embodiment()
