import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from config import Config
from core.agent_state import StateMachine
from core.engine.cognitive_engine import CognitiveEngine
from core.memory import MemoryManager
from core.writer_lease import (
    ProcessWriterLease,
    WriterLeaseState,
    WriterLeaseUnavailable,
)


ROOT = Path(__file__).resolve().parents[1]


class WriterLeaseTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.lease_path = Path(self.temp_dir.name) / "writer.lock"

    def test_same_process_contention_is_typed_and_release_is_reusable(self):
        owner = ProcessWriterLease(self.lease_path)
        contender = ProcessWriterLease(self.lease_path)
        self.addCleanup(owner.close)
        self.addCleanup(contender.close)

        self.assertEqual(owner.state, WriterLeaseState.NEW)
        owner.acquire()
        self.assertEqual(owner.state, WriterLeaseState.HELD)

        with self.assertRaises(WriterLeaseUnavailable):
            contender.acquire()
        self.assertEqual(contender.state, WriterLeaseState.NEW)

        owner.close()
        self.assertEqual(owner.state, WriterLeaseState.RELEASED)
        contender.acquire()
        self.assertEqual(contender.state, WriterLeaseState.HELD)
        contender.close()
        contender.close()
        self.assertEqual(contender.state, WriterLeaseState.RELEASED)

    def test_other_process_fails_fast_then_can_acquire_after_release(self):
        script = "\n".join(
            (
                "import sys",
                "from core.writer_lease import ProcessWriterLease, WriterLeaseUnavailable",
                "lease = ProcessWriterLease(sys.argv[1])",
                "try:",
                "    lease.acquire()",
                "except WriterLeaseUnavailable:",
                "    raise SystemExit(23)",
                "lease.close()",
            )
        )

        def run_contender():
            return subprocess.run(
                [sys.executable, "-c", script, os.fspath(self.lease_path)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

        owner = ProcessWriterLease(self.lease_path).acquire()
        self.addCleanup(owner.close)
        blocked = run_contender()
        self.assertEqual(
            blocked.returncode,
            23,
            blocked.stdout + blocked.stderr,
        )

        owner.close()
        acquired = run_contender()
        self.assertEqual(
            acquired.returncode,
            0,
            acquired.stdout + acquired.stderr,
        )

    def test_process_death_releases_os_lock_for_handoff(self):
        script = "\n".join(
            (
                "import os, sys, time",
                "from core.writer_lease import ProcessWriterLease",
                "ProcessWriterLease(sys.argv[1]).acquire()",
                "print('held', flush=True)",
                "time.sleep(0.5)",
                "os._exit(0)",
            )
        )
        process = subprocess.Popen(
            [sys.executable, "-c", script, os.fspath(self.lease_path)],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.addCleanup(
            lambda: process.kill() if process.poll() is None else None
        )
        self.assertEqual(process.stdout.readline().strip(), "held")

        with self.assertRaises(WriterLeaseUnavailable):
            ProcessWriterLease(self.lease_path).acquire()

        _, stderr = process.communicate(timeout=10)
        self.assertEqual(process.returncode, 0, stderr)
        next_owner = ProcessWriterLease(self.lease_path).acquire()
        next_owner.close()

    def test_configured_lease_path_is_absolute_and_under_output_dir(self):
        output_dir = Path(Config.OUTPUT_DIR)
        if not output_dir.is_absolute():
            output_dir = Path(Config.BASE_DIR) / output_dir

        self.assertTrue(Path(Config.MEMORY_WRITER_LEASE_FILE).is_absolute())
        self.assertEqual(
            Path(Config.MEMORY_WRITER_LEASE_FILE).parent.resolve(),
            output_dir.resolve(),
        )


class MemoryManagerLeaseTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.lease_path = Path(self.temp_dir.name) / "writer.lock"
        self.config_patch = patch.object(
            Config,
            "MEMORY_WRITER_LEASE_FILE",
            os.fspath(self.lease_path),
        )
        self.config_patch.start()
        self.addCleanup(self.config_patch.stop)

    def test_contention_fails_before_vector_store_construction(self):
        owner = ProcessWriterLease(self.lease_path).acquire()
        self.addCleanup(owner.close)

        with patch("core.memory.VectorStore") as vector_store:
            with self.assertRaises(WriterLeaseUnavailable):
                MemoryManager(Mock())

        vector_store.assert_not_called()

    def test_vector_store_init_failure_returns_lease(self):
        with patch(
            "core.memory.VectorStore",
            side_effect=RuntimeError("store init failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "store init failed"):
                MemoryManager(Mock())

        next_owner = ProcessWriterLease(self.lease_path).acquire()
        next_owner.close()

    def test_close_releases_lease(self):
        with patch("core.memory.VectorStore", return_value=Mock()):
            manager = MemoryManager(Mock())

        with self.assertRaises(WriterLeaseUnavailable):
            ProcessWriterLease(self.lease_path).acquire()

        manager.close()
        next_owner = ProcessWriterLease(self.lease_path).acquire()
        next_owner.close()
        manager.close()


class _Stopper:
    def __init__(self, result=True):
        self.result = result

    def shutdown(self, **kwargs):
        return self.result

    def stop(self, **kwargs):
        return self.result


def _shutdown_engine(*, actor_result=True):
    engine = CognitiveEngine.__new__(CognitiveEngine)
    engine._owns_memory = True
    engine.state_machine = StateMachine()
    engine._runtime_mutation_gate = threading.Lock()
    engine._shutdown_lock = threading.Lock()
    engine._shutdown_complete = False
    engine._shutdown_result = None
    engine.interaction_actor = _Stopper(actor_result)
    engine.autonomous = _Stopper()
    engine.reader = Mock()
    engine.ego = Mock()
    engine.memory = Mock()
    return engine


class CognitiveEngineLeaseLifecycleTests(unittest.TestCase):
    def test_clean_shutdown_closes_owned_memory_once(self):
        engine = _shutdown_engine()

        self.assertTrue(engine.shutdown())
        self.assertTrue(engine.shutdown())
        engine.ego.save_state.assert_called_once_with()
        engine.memory.close.assert_called_once_with()

    def test_worker_degraded_shutdown_retains_writer_lease(self):
        engine = _shutdown_engine(actor_result=False)

        self.assertFalse(engine.shutdown())
        engine.ego.save_state.assert_not_called()
        engine.memory.close.assert_not_called()

    def test_optional_cleanup_failure_retains_writer_lease(self):
        engine = _shutdown_engine()
        engine.reader.stop.side_effect = RuntimeError("reader still alive")

        self.assertFalse(engine.shutdown())
        engine.ego.save_state.assert_called_once_with()
        engine.memory.close.assert_not_called()

    def test_engine_init_failure_closes_internally_owned_memory(self):
        events = []
        memory = Mock()
        memory.close.side_effect = lambda: events.append("memory")
        actor = Mock()
        actor.shutdown.side_effect = lambda **kwargs: events.append("actor") or True
        autonomous = Mock()
        autonomous.stop.side_effect = (
            lambda **kwargs: events.append("autonomous") or True
        )
        reader = Mock()
        reader.stop.side_effect = lambda: events.append("reader")

        def fail_initialize(engine, **kwargs):
            engine.memory = memory
            engine.interaction_actor = actor
            engine.autonomous = autonomous
            engine.reader = reader
            raise RuntimeError("late init failure")

        with patch.object(
            CognitiveEngine,
            "_initialize",
            new=fail_initialize,
        ):
            with self.assertRaisesRegex(RuntimeError, "late init failure"):
                CognitiveEngine()

        memory.close.assert_called_once_with()
        self.assertEqual(events, ["actor", "autonomous", "reader", "memory"])

    def test_engine_init_failure_retains_lease_if_partial_worker_survives(self):
        memory = Mock()
        actor = Mock()
        actor.shutdown.return_value = False

        def fail_initialize(engine, **kwargs):
            engine.memory = memory
            engine.interaction_actor = actor
            raise RuntimeError("late init failure")

        with patch.object(
            CognitiveEngine,
            "_initialize",
            new=fail_initialize,
        ):
            with self.assertRaisesRegex(RuntimeError, "late init failure"):
                CognitiveEngine()

        actor.shutdown.assert_called_once()
        memory.close.assert_not_called()


class WriterDeploymentContractTests(unittest.TestCase):
    def test_brain_and_chroma_are_singleton_recreate_deployments(self):
        for filename in ("brain-deployment.yaml", "chroma-deployment.yaml"):
            manifest = (ROOT / "k8s" / filename).read_text(encoding="utf-8")
            deployment = manifest.split("---", 1)[0]
            self.assertIn("replicas: 1", deployment, filename)
            self.assertIn("strategy:\n    type: Recreate", deployment, filename)
            self.assertIn(
                "terminationGracePeriodSeconds: 60",
                deployment,
                filename,
            )

    def test_migration_uses_the_runtime_writer_lease(self):
        import migrate_db

        owner = ProcessWriterLease(
            Config.MEMORY_WRITER_LEASE_FILE
        ).acquire()
        self.addCleanup(owner.close)
        with patch.object(migrate_db, "_migrate_locked") as migrate_locked:
            with self.assertRaises(WriterLeaseUnavailable):
                migrate_db.migrate()
        migrate_locked.assert_not_called()

        owner.close()
        with patch.object(
            migrate_db,
            "_migrate_locked",
            return_value="done",
        ) as migrate_locked:
            self.assertEqual(migrate_db.migrate(), "done")
        migrate_locked.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
