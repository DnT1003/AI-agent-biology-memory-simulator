import os
import sys
import unittest
from unittest.mock import MagicMock, patch
import json

# Ensure project root on path
sys.path.insert(0, os.path.abspath(os.getcwd()))

from core.engine.perception import PerceptionController
from core.self_model import SelfModel
from components.llm import LLM

class TestSensoryIntegration(unittest.TestCase):
    def setUp(self):
        self.mock_engine = MagicMock()
        self.mock_engine.ego = SelfModel()
        # Mock local_perception behavior
        self.mock_engine.local_perception.analyze.return_value = {
            "valence": 0.5, "arousal": 0.8, "importance": 0.5
        }
        self.perception = PerceptionController(self.mock_engine)

    def test_environmental_context(self):
        print("\n--- Testing Environmental Context (Time/Storage) ---")
        ctx = self.perception.get_environmental_context()
        print(f"Captured Context: {ctx}")
        self.assertIn("[MÔI TRƯỜNG]", ctx)

    def test_sensory_summary_injection(self):
        print("\n--- Testing Sensory Summary Injection ---")
        summary = self.perception.get_sensory_summary("Hello, I am happy!")
        print(f"Summary:\n{summary}")
        self.assertIn("--- HỆ THỐNG CẢM GIÁC (SENSORY INPUT) ---", summary)
        self.assertIn("[SINH LÝ]", summary)
        self.assertIn("[SẮC THÁI USER]", summary)
        self.assertIn("Tích cực/Vui vẻ (Kích động)", summary)

    @patch('PIL.Image.open')
    @patch('google.genai.Client')
    def test_llm_vision_call(self, mock_client_class, mock_img_open):
        print("\n--- Testing LLM Multimodal (Vision) call ---")
        mock_client = mock_client_class.return_value
        mock_resp = MagicMock()
        mock_resp.text = '{"valence": 0.8, "arousal": 0.3, "description": "A cute cat"}'
        mock_client.models.generate_content.return_value = mock_resp
        
        ego = SelfModel()
        llm = LLM(ego=ego)
        llm.client = mock_client
        
        # Test see() triggers LLM with image
        ego.see("mock_path.jpg", llm)
        
        # Verify call arguments
        args, kwargs = mock_client.models.generate_content.call_args
        contents = kwargs.get('contents')
        self.assertEqual(len(contents), 2) # Prompt + Image object
        self.assertAlmostEqual(ego.mood, 0.24, places=2) # 0.0 + (0.8 * 0.3 * 1.0)
        self.assertLess(ego.dopamine_receptors, 1.0) # Downregulation check

if __name__ == "__main__":
    unittest.main()
