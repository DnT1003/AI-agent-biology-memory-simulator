import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from config import Config
from core.engine.memory_ops import MemoryOperationsController
from core.skills import Skill, SkillRegistry


DAY = 86400.0


def _skill(name="search"):
    skill = Skill(name, "Search", "ACTION", lambda value: value)
    skill.mastery = 0.8
    skill.rust_level = 0.1
    skill.last_used = 0.0
    return skill


class SkillDecayCheckpointM2Tests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.skills_file = str(Path(self.temp_dir.name) / "skills.json")
        self.config_patch = patch.object(Config, "SKILLS_FILE", self.skills_file)
        self.config_patch.start()

    def tearDown(self):
        self.config_patch.stop()
        self.temp_dir.cleanup()

    def test_no_skill_call_persists_and_advances_its_own_clock(self):
        registry = SkillRegistry()

        self.assertEqual(registry.decay_skills_by_clock(now=10 * DAY), 0.0)
        state = json.loads(Path(self.skills_file).read_text(encoding="utf-8"))
        self.assertEqual(state["__meta__"]["skill_decay_checkpoint_at"], 10 * DAY)

        self.assertEqual(registry.decay_skills_by_clock(now=12 * DAY), 2.0)
        state = json.loads(Path(self.skills_file).read_text(encoding="utf-8"))
        self.assertEqual(state["__meta__"]["skill_decay_checkpoint_at"], 12 * DAY)

    def test_elapsed_interval_survives_reload(self):
        first = SkillRegistry()
        first.register(_skill())
        first.decay_skills_by_clock(now=10 * DAY)

        reloaded = SkillRegistry()
        skill = _skill()
        reloaded.register(skill)
        reloaded.load()

        elapsed = reloaded.decay_skills_by_clock(now=12 * DAY)

        self.assertEqual(elapsed, 2.0)
        self.assertAlmostEqual(skill.mastery, 0.7)
        self.assertAlmostEqual(skill.rust_level, 0.3)

    def test_save_failure_rolls_back_decay_and_checkpoint_for_exact_retry(self):
        registry = SkillRegistry()
        skill = _skill()
        registry.register(skill)
        registry.decay_skills_by_clock(now=10 * DAY)

        with patch("core.utils.atomic_write_json", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                registry.decay_skills_by_clock(now=12 * DAY)

        self.assertEqual(registry._skill_decay_checkpoint_at, 10 * DAY)
        self.assertEqual(skill.mastery, 0.8)
        self.assertEqual(skill.rust_level, 0.1)

        self.assertEqual(registry.decay_skills_by_clock(now=12 * DAY), 2.0)
        self.assertAlmostEqual(skill.mastery, 0.7)
        self.assertAlmostEqual(skill.rust_level, 0.3)

    def test_failed_legacy_baseline_can_be_retried_without_retroactive_decay(self):
        registry = SkillRegistry()
        skill = _skill()
        registry.register(skill)

        with patch("core.utils.atomic_write_json", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                registry.decay_skills_by_clock(now=20 * DAY)

        self.assertIsNone(registry._skill_decay_checkpoint_at)
        self.assertEqual(skill.mastery, 0.8)
        self.assertEqual(registry.decay_skills_by_clock(now=20 * DAY), 0.0)
        self.assertEqual(skill.mastery, 0.8)

    def test_legacy_state_migrates_without_retroactive_decay(self):
        Path(self.skills_file).write_text(
            json.dumps(
                {
                    "search": {
                        "mastery": 0.65,
                        "rust_level": 0.2,
                        "last_used": 0.0,
                    }
                }
            ),
            encoding="utf-8",
        )
        registry = SkillRegistry()
        skill = _skill()
        registry.register(skill)
        registry.load()

        self.assertIsNone(registry._skill_decay_checkpoint_at)
        self.assertEqual(registry.decay_skills_by_clock(now=50 * DAY), 0.0)
        self.assertEqual(skill.mastery, 0.65)
        self.assertEqual(skill.rust_level, 0.2)
        state = json.loads(Path(self.skills_file).read_text(encoding="utf-8"))
        self.assertEqual(state["__meta__"]["skill_decay_checkpoint_at"], 50 * DAY)

    def test_explicit_days_api_remains_supported(self):
        registry = SkillRegistry()
        skill = _skill()
        registry.register(skill)

        with patch("core.skills.time.time", return_value=10 * DAY):
            result = registry.decay_skills(days_passed=2.0)

        self.assertIsNone(result)
        self.assertAlmostEqual(skill.mastery, 0.7)
        self.assertAlmostEqual(skill.rust_level, 0.3)
        state = json.loads(Path(self.skills_file).read_text(encoding="utf-8"))
        self.assertIn("__meta__", state)
        self.assertNotIn("skill_decay_checkpoint_at", state["__meta__"])

    def test_sleep_uses_skill_clock_even_when_memory_collection_is_empty(self):
        registry = SkillRegistry()
        skill = _skill()
        registry.register(skill)
        controller = object.__new__(MemoryOperationsController)
        controller.engine = SimpleNamespace(
            memory=SimpleNamespace(get_all=lambda: [], remove_many=lambda _ids: None),
            skills=registry,
            ego=SimpleNamespace(stress=0.0),
        )

        with patch("core.engine.memory_ops.time.time", return_value=10 * DAY):
            controller._decay_phase()
        with patch("core.engine.memory_ops.time.time", return_value=12 * DAY):
            controller._decay_phase()

        self.assertAlmostEqual(skill.mastery, 0.7)
        self.assertAlmostEqual(skill.rust_level, 0.3)
        state = json.loads(Path(self.skills_file).read_text(encoding="utf-8"))
        self.assertEqual(
            state["__meta__"]["skill_decay_checkpoint_at"],
            12 * DAY,
        )


if __name__ == "__main__":
    unittest.main()
