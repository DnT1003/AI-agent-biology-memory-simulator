import json
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from config import Config
from core.engine.memory_ops import MemoryOperationsController
from core.skills import SkillRegistry, validate_dynamic_skill_name, validate_dynamic_skill_source


SAFE_SOURCE = '''DESCRIPTION = "Uppercase text"
USAGE = "ACTION: safe_tool | <text>"

def safe_tool(args):
    """Return uppercase input."""
    return args.upper()
'''


class DynamicSkillSecurityTests(unittest.TestCase):
    def _controller(self, llm):
        engine = SimpleNamespace(
            short_term_buffer=["User: please create a tool"],
            stm_lock=threading.Lock(),
            llm=llm,
            skills=SimpleNamespace(
                get_prompt_instructions=Mock(return_value="No matching tool"),
                load_dynamic_skills=Mock(),
            ),
        )
        controller = object.__new__(MemoryOperationsController)
        controller.engine = engine
        return controller, engine

    def test_disabled_workshop_has_no_llm_or_file_side_effect(self):
        llm = Mock()
        controller, _ = self._controller(llm)

        with patch.object(Config, "ALLOW_DYNAMIC_SKILLS", False):
            controller._tool_workshop_phase()

        llm.generate_text.assert_not_called()

    def test_name_and_source_validators_reject_escape_primitives(self):
        for name in ("../../main", "C:\\temp\\main", "/tmp/main", "__init__", "công_cụ"):
            with self.subTest(name=name):
                self.assertFalse(validate_dynamic_skill_name(name)[0])

        for source in (
            "import os\ndef safe_tool(args): return args",
            "def safe_tool(args): return open(args).read()",
            "def safe_tool(args): return args.__class__",
            "import uuid\ndef safe_tool(args): return uuid.os.system(args)",
            "import dataclasses\ndef safe_tool(args): return dataclasses.sys.modules['os'].system(args)",
            "print('top-level side effect')\ndef safe_tool(args): return args",
        ):
            with self.subTest(source=source):
                self.assertFalse(validate_dynamic_skill_source(source)[0])

    def test_invalid_name_is_rejected_before_code_generation(self):
        llm = Mock()
        llm.generate_text.return_value = (
            json.dumps({"has_gap": True, "tool_name": "../../main", "description": "escape"}),
            0.0,
        )
        controller, _ = self._controller(llm)

        with patch.object(Config, "ALLOW_DYNAMIC_SKILLS", True), patch("builtins.print"):
            controller._tool_workshop_phase()

        self.assertEqual(llm.generate_text.call_count, 1)

    def test_unsafe_source_is_rejected_before_write(self):
        llm = Mock()
        llm.generate_text.side_effect = [
            (json.dumps({"has_gap": True, "tool_name": "safe_tool", "description": "test"}), 0.0),
            ("import os\ndef safe_tool(args): return os.getcwd()", 0.0),
        ]
        controller, _ = self._controller(llm)

        with TemporaryDirectory() as temp_dir, patch.object(Config, "ALLOW_DYNAMIC_SKILLS", True), patch(
            "core.skills.DYNAMIC_SKILL_CANDIDATES_DIR", Path(temp_dir) / "dynamic_skill_candidates"
        ), patch.object(
            Config, "OUTPUT_DIR", temp_dir
        ), patch("builtins.print"):
            controller._tool_workshop_phase()
            self.assertFalse((Path(temp_dir) / "dynamic_skill_candidates" / "safe_tool.py").exists())

    def test_valid_source_is_created_once_and_never_overwritten(self):
        gap = json.dumps({"has_gap": True, "tool_name": "safe_tool", "description": "test"})
        llm = Mock()
        llm.generate_text.side_effect = [(gap, 0.0), (SAFE_SOURCE, 0.0)]
        controller, engine = self._controller(llm)

        with TemporaryDirectory() as temp_dir, patch.object(Config, "ALLOW_DYNAMIC_SKILLS", True), patch(
            "core.skills.DYNAMIC_SKILL_CANDIDATES_DIR", Path(temp_dir) / "dynamic_skill_candidates"
        ), patch.object(
            Config, "OUTPUT_DIR", temp_dir
        ), patch("builtins.print"):
            controller._tool_workshop_phase()
            target = Path(temp_dir) / "dynamic_skill_candidates" / "safe_tool.py"
            self.assertEqual(target.read_text(encoding="utf-8"), SAFE_SOURCE.strip())
            engine.skills.load_dynamic_skills.assert_not_called()

            llm.generate_text.side_effect = [(gap, 0.0), (SAFE_SOURCE.replace("upper", "lower"), 0.0)]
            controller._tool_workshop_phase()
            self.assertEqual(target.read_text(encoding="utf-8"), SAFE_SOURCE.strip())
            engine.skills.load_dynamic_skills.assert_not_called()

    def test_operator_approved_safe_skill_loads_and_executes(self):
        with TemporaryDirectory() as temp_dir:
            approved_dir = Path(temp_dir) / "approved_dynamic_skills"
            approved_dir.mkdir()
            (approved_dir / "safe_tool.py").write_text(SAFE_SOURCE, encoding="utf-8")
            skills_state = Path(temp_dir) / "skills.json"

            with patch.object(Config, "ALLOW_DYNAMIC_SKILLS", True), patch(
                "core.skills.DYNAMIC_SKILLS_DIR", approved_dir
            ), patch.object(Config, "SKILLS_FILE", str(skills_state)), patch("builtins.print"):
                registry = SkillRegistry()
                registry.load_dynamic_skills()
                result = registry.execute("safe_tool", "hello")

            self.assertIn("safe_tool", registry.skills)
            self.assertEqual(result, "HELLO")


if __name__ == "__main__":
    unittest.main()
