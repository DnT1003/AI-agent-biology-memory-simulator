import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from components.llm import LLM
from core.engine.bio_controller import BioController
from core.self_model import SelfModel


def _llm(ego):
    instance = LLM.__new__(LLM)
    instance.settings = SimpleNamespace(provider="gemini")
    instance.local_llm = Mock()
    instance.ego = ego
    instance.client = None
    return instance


_EXHAUSTED_EGO = SimpleNamespace(fatigue=0.95, stress=0.95)


class BioThrottleFlagTests(unittest.TestCase):
    def test_throttling_still_applies_by_default(self):
        prompt, params = _llm(_EXHAUSTED_EGO)._apply_cognitive_throttling("p", 0.1, None)
        self.assertNotEqual(params["temperature"], 0.1)
        self.assertEqual(params["max_output_tokens"], 150)
        self.assertIn("[CẢNH BÁO SINH LÝ]", prompt)

    def test_disabled_throttling_leaves_request_untouched(self):
        prompt, params = _llm(_EXHAUSTED_EGO)._apply_cognitive_throttling(
            "p", 0.1, None, enabled=False
        )
        self.assertEqual(prompt, "p")
        self.assertEqual(
            params, {"temperature": 0.1, "top_p": 1.0, "max_output_tokens": None}
        )

    def _call(self, method, retry_name, **kwargs):
        llm = _llm(_EXHAUSTED_EGO)
        with patch.object(llm, "_use_local_for_request", return_value=False), \
                patch.object(llm, retry_name, return_value=("ok", 0.0)) as retry:
            getattr(llm, method)("extract", temperature=0.1, **kwargs)
        return retry.call_args.args

    def test_generate_text_honors_bio_throttle_false(self):
        args = self._call("generate_text", "_generate_text_with_retry", bio_throttle=False)
        self.assertEqual(args[:5], ("extract", 0.1, 1.0, None, None))

    def test_generate_json_honors_bio_throttle_false(self):
        args = self._call("generate_json", "_generate_json_with_retry", bio_throttle=False)
        self.assertEqual(args[:5], ("extract", 0.1, 1.0, None, None))

    def test_generate_text_throttles_persona_calls(self):
        args = self._call("generate_text", "_generate_text_with_retry")
        self.assertEqual(args[4], 150)


def _ego(**overrides):
    ego = SelfModel.__new__(SelfModel)
    ego.lock = threading.Lock()
    ego.mood = 0.5
    ego.stress = 0.1
    ego.fatigue = 0.0
    ego.integrity = 1.0
    ego.atp_level = 1.0
    ego.dopamine_receptors = 1.0
    ego.resilience = 0.0
    ego.is_stranger = False
    ego.mood_anchor = None
    ego.mood_anchor_duration = 0.0
    ego.bio_controller = BioController()
    for name, value in overrides.items():
        setattr(ego, name, value)
    return ego


class SelfModelSemanticsTests(unittest.TestCase):
    def test_update_state_reports_shock_on_sharp_drop(self):
        ego = _ego()
        with patch("builtins.print"):
            self.assertTrue(ego.update_state({"valence": -1.0, "arousal": 0.0}))

    def test_update_state_mild_input_is_not_shock(self):
        ego = _ego()
        with patch("builtins.print"):
            self.assertFalse(ego.update_state({"valence": 0.3, "arousal": 0.0}))
            self.assertFalse(ego.update_state({"valence": 0.3, "arousal": 0.0}))

    def test_low_integrity_prompt_describes_identity_not_atp(self):
        prompt = _ego(integrity=0.2).get_interoceptive_prompt()
        self.assertIn("BẢN NGÃ", prompt)
        self.assertNotIn("ATP", prompt)


if __name__ == "__main__":
    unittest.main()
