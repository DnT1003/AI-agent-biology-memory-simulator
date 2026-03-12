import os
import sys
import unittest
from unittest.mock import MagicMock, patch
import time

# Ensure project root on path
sys.path.insert(0, os.path.abspath(os.getcwd()))

from core.self_model import SelfModel
from components.llm import LLM

class TestIntrinsicMotivation(unittest.TestCase):
    def test_drive_status(self):
        print("\n--- Testing Drive Status Logic ---")
        ego = SelfModel()
        ego.social_need = 0.9
        ego.curiosity = 0.5
        ego.fatigue = 0.2
        
        status = ego.get_drive_status()
        print(f"Social Need is 0.9. Dominant: {status['dominant']}")
        self.assertEqual(status['dominant'], "social")
        self.assertEqual(status['dominant_value'], 0.9)
        
        ego.curiosity = 0.95
        status = ego.get_drive_status()
        self.assertEqual(status['dominant'], "curiosity")

    def test_llm_throttling(self):
        print("\n--- Testing LLM Cognitive Throttling ---")
        ego = MagicMock()
        ego.fatigue = 0.9
        ego.stress = 0.1
        
        llm = LLM(ego=ego)
        llm.client = MagicMock()
        
        prompt = "Hello, how are you today?"
        
        # Mock generate_content to return a mock response
        mock_resp = MagicMock()
        mock_resp.text = "Gọn."
        llm.client.models.generate_content.return_value = mock_resp
        
        # Test generate_text
        llm.generate_text(prompt)
        
        # Verify that warning was appended to prompt
        args, kwargs = llm.client.models.generate_content.call_args
        # In the new implementation, prompt is updated before calling generate_content
        sent_prompt = kwargs.get('contents') or args[1] 
        self.assertIn("[CẢNH BÁO SINH LÝ]", sent_prompt)
        self.assertIn("TRẢ LỜI CỰC NGẮN GỌN", sent_prompt)
        
        # Verify max_output_tokens was limited
        config = kwargs.get('config')
        self.assertEqual(config.max_output_tokens, 150)

if __name__ == "__main__":
    unittest.main()
