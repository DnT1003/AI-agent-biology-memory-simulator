import os
import sys
import unittest
from unittest.mock import MagicMock

# Ensure project root on path
sys.path.insert(0, os.path.abspath(os.getcwd()))

from core.memory import MemoryManager, MemoryTrace, MemoryType
from components.embedder import Embedder

class TestHybridMemory(unittest.TestCase):
    def setUp(self):
        self.embedder = Embedder()
        self.memory = MemoryManager(self.embedder)

    def test_add_and_search_remote(self):
        print("\n--- Testing Add and Search (Remote Server) ---")
        trace = MemoryTrace(
            content="This is a test memory for the hybrid architecture.",
            type=MemoryType.EPISODIC,
            valence=0.5,
            arousal=0.2,
            importance=0.8
        )
        
        # Clear existing for clean test
        print("Clearing collection...")
        self.memory.store.clear_all()
        import time
        time.sleep(1) # Allow for server to sync
        
        # Add
        print(f"Adding memory... (Using Collection ID: {self.memory.store.collection.id})")
        self.memory.add_memory(trace)
        print("Memory added.")
        
        # Search
        results = self.memory.search_memories("hybrid architecture", top_k=1)
        self.assertEqual(len(results), 1)
        similarity, result_trace = results[0]
        print(f"Search Result: {result_trace.content} (Similarity: {similarity:.2f})")
        self.assertIn("hybrid architecture", result_trace.content)
        self.assertEqual(result_trace.id, trace.id)

if __name__ == "__main__":
    unittest.main()
