import os
import sys
import unittest
from unittest.mock import MagicMock, patch
import time

# Ensure project root on path
sys.path.insert(0, os.path.abspath(os.getcwd()))

from core.world_graph import WorldGraph
from core.engine.interaction import InteractionController

class TestWorldGraphV2(unittest.TestCase):
    def setUp(self):
        self.db_path = "outputs/test_world_graph_v2.json"
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        self.wg = WorldGraph(filepath=self.db_path)
        
    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_valence_extraction_and_storage(self):
        print("\n--- Testing Valence Extraction and Storage ---")
        mock_llm = MagicMock()
        # Giả lập trả về quan hệ có valence từ Local LLM
        mock_llm.generate_json.return_value = [
            {"source": "User", "relation": "ghét", "target": "John", "valence": -0.8}
        ]
        
        text = "Tôi thực sự ghét thằng John đó."
        self.wg.update_from_text(text, mock_llm)
        
        # Kiểm tra storage
        facts = self.wg.query("John")
        print(f"Query 'John': {facts}")
        self.assertTrue(any("valence:-0.8" in f for f in facts))
        self.assertTrue(any("User ghét John" in f for f in facts))

    def test_interaction_context_injection(self):
        print("\n--- Testing Interaction Context Injection ---")
        
        engine = MagicMock()
        engine.world_graph = self.wg
        engine.memory.get_all.return_value = []
        engine.memory_ops._apply_fog_masking = lambda x: x
        engine.skills.get_prompt_instructions.return_value = ""
        engine.reader.get_status.return_value = "Ready"
        engine.value_system.get_moral_context.return_value = ""
        
        class MockEgo:
            def __init__(self):
                self.stress = 0.0
                self.fatigue = 0.0
                self.atp_level = 1.0
                self.energy = 1.0
                self.curiosity = 0.5
                self.fatigue_critical = 0.9
            def update_state(self, *a, **kw): pass
        
        engine.ego = MockEgo()
        engine.short_term_buffer = []
        engine.llm.generate_json.return_value = {
            "thought": "Thinking...",
            "response": "Hello",
            "valence": 0.5,
            "arousal": 0.5
        }

        # Thêm dữ liệu vào graph
        self.wg.add_relation("User", "yêu", "Mẹ", valence=0.9)
        
        controller = InteractionController(engine)
        
        # Giả lập input chứa thực thể "Mẹ"
        user_input = "Mẹ tôi dạo này thế nào nhỉ?"
        
        # Test patch get_perceive_prompt to capture its arguments
        with patch('core.engine.interaction.get_perceive_prompt') as mock_prompt_gen:
            with patch('core.engine.interaction.print'): # Suppress print
                controller.perceive_and_respond(user_input, [])
                
                # Check call arguments
                args, kwargs = mock_prompt_gen.call_args
                mem_context = args[3] # 4th argument is mem_context
                
                print(f"Injected Context snippet: {mem_context[:200]}...")
                self.assertIn("[SOCIAL ATTITUDE]", mem_context)
                self.assertIn("User yêu Mẹ [valence:+0.9]", mem_context)
                self.assertIn("thân thiện", mem_context)

if __name__ == "__main__":
    unittest.main()
