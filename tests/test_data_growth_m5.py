import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from config import Config
from core.engine.autonomous import AutonomousController
from core.engine.context_compressor import ContextCompressor
from core.memory import MemoryType

from tests.test_runtime_p0 import _make_tick_engine


class MemoryMaintenanceCadenceTests(unittest.TestCase):
    def _tick(self, engine):
        with patch("core.engine.cognitive_engine.os.path.exists", return_value=False):
            return engine._cognitive_tick_owned(30.0)

    def test_back_to_back_ticks_read_the_store_once(self):
        engine = _make_tick_engine()
        engine.memory.get_all = Mock(wraps=engine.memory.get_all)
        self.assertTrue(self._tick(engine))
        self.assertTrue(self._tick(engine))
        self.assertTrue(self._tick(engine))
        self.assertEqual(engine.memory.gc_calls, 1)
        self.assertEqual(engine.memory.get_all.call_count, 1)

    def test_biology_still_advances_on_skipped_maintenance_ticks(self):
        engine = _make_tick_engine()
        self._tick(engine)
        before = engine.ego.biological_calls
        self._tick(engine)
        self.assertEqual(engine.ego.biological_calls, before + 1)

    def test_maintenance_runs_again_after_interval(self):
        engine = _make_tick_engine()
        self._tick(engine)
        engine._last_memory_maintenance_at -= Config.MEMORY_MAINTENANCE_INTERVAL_SECONDS + 1
        self._tick(engine)
        self.assertEqual(engine.memory.gc_calls, 2)

    def test_metabolic_gc_request_runs_immediately(self):
        engine = _make_tick_engine()
        self._tick(engine)
        engine.ego.apply_circadian_rhythm_deferred = lambda: True
        self._tick(engine)
        self.assertEqual(engine.memory.gc_calls, 2)


class FinetuneQueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.queue = os.path.join(self.tmp.name, "out", "slm_finetune_data.txt")
        patcher = patch.object(Config, "SLM_FINETUNE_QUEUE_FILE", self.queue)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _read(self):
        with open(self.queue, encoding="utf-8") as f:
            return f.read()

    def test_same_rejected_chunk_is_queued_once(self):
        compressor = ContextCompressor()
        compressor._route_to_background_training(["ký ức A"])
        compressor._route_to_background_training(["ký ức A", "ký ức B"])
        self.assertEqual(self._read(), "ký ức A\n\nký ức B\n\n")

    def test_queue_stops_growing_at_its_cap(self):
        compressor = ContextCompressor()
        with patch.object(Config, "SLM_FINETUNE_QUEUE_MAX_BYTES", 40):
            compressor._route_to_background_training(["x" * 30])
            compressor._route_to_background_training(["y" * 30])
        self.assertEqual(self._read(), "x" * 30 + "\n\n")

    def test_trainer_consumes_the_file_the_compressor_writes(self):
        # slm_trainer imports torch at module load, so check its source instead.
        path = os.path.join(os.path.dirname(Config.BASE_DIR), os.path.basename(Config.BASE_DIR),
                            "core", "engine", "slm_trainer.py")
        with open(path, encoding="utf-8") as f:
            source = f.read()
        self.assertIn("queue_path = Config.SLM_FINETUNE_QUEUE_FILE", source)


class StatePathTests(unittest.TestCase):
    def test_value_and_world_files_follow_output_dir(self):
        self.assertEqual(Config.VALUES_FILE, os.path.join(Config.OUTPUT_DIR, "values.json"))
        self.assertEqual(Config.WORLD_GRAPH_FILE, os.path.join(Config.OUTPUT_DIR, "world_graph.json"))

    def test_engine_constructs_stores_with_configured_paths(self):
        import inspect
        from core.engine import cognitive_engine

        source = inspect.getsource(cognitive_engine.CognitiveEngine._initialize)
        self.assertIn("WorldGraph(Config.WORLD_GRAPH_FILE)", source)
        self.assertIn("ValueSystem(Config.VALUES_FILE)", source)


class ReadingMemoryTypeTests(unittest.TestCase):
    def test_reading_is_stored_as_fading_episodic_memory(self):
        added = []
        engine = SimpleNamespace(
            reader=SimpleNamespace(
                get_next_reading_material=lambda: ("[Sách]: Truyện Kiều", "Trăm năm..."),
                last_material_new_book=False,
            ),
            ego=SimpleNamespace(get_bio_state_dict=lambda: {}, register_reward=Mock()),
            llm=SimpleNamespace(generate_text=Mock(return_value=("Tóm tắt", 0.0))),
            memory=SimpleNamespace(add_memory=added.append),
        )
        controller = AutonomousController(engine)
        with patch("builtins.print"):
            controller._do_reading_session()
        self.assertEqual(MemoryType(added[0].type), MemoryType.EPISODIC)
        self.assertLess(added[0].importance, 0.9)
        engine.ego.register_reward.assert_called_once_with("reading", 0.4)


if __name__ == "__main__":
    unittest.main()
