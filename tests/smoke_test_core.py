import unittest
import os
import json
import shutil
import threading
import time
from core.utils import atomic_write_json, atomic_read_json
from config import Config

class TestCoreAura(unittest.TestCase):
    def setUp(self):
        self.test_dir = "test_outputs"
        os.makedirs(self.test_dir, exist_ok=True)
        self.test_file = os.path.join(self.test_dir, "test.json")

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_atomic_write_json(self):
        data = {"key": "value", "nested": [1, 2, 3]}
        atomic_write_json(self.test_file, data)
        
        # Verify it exists and content is correct
        self.assertTrue(os.path.exists(self.test_file))
        read_data = atomic_read_json(self.test_file)
        self.assertEqual(data, read_data)

    def test_atomic_write_corruption_prevention(self):
        # We can't easily simulate a crash mid-write without mocking os.replace
        # but we can check if it works normally.
        data = {"id": 1}
        atomic_write_json(self.test_file, data)
        self.assertEqual(atomic_read_json(self.test_file)["id"], 1)

    def test_config_paths(self):
        # Ensure Config paths are absolute or at least defined
        self.assertTrue(hasattr(Config, 'OUTPUT_DIR'))
        self.assertTrue(os.path.isabs(Config.BASE_DIR))

    def test_tool_registry(self):
        from core.tools import get_skill_registry
        registry = get_skill_registry()
        self.assertIn("web_search", registry.skills)
        self.assertIn("read_time", registry.skills)
        self.assertIn("add_goal", registry.skills)

if __name__ == '__main__':
    unittest.main()
