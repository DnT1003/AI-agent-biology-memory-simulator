import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.engine.interaction import InteractionController
from core.sim_week import run_week
from core.style_filter import humanize

NL = chr(10)


class HumanizeTests(unittest.TestCase):
    def test_markdown_list_becomes_one_spoken_sentence(self):
        reply = NL.join([
            "Chắc chắn rồi!", "## Gợi ý cho anh", "- **Đi ngủ sớm** nhé", "- Uống nước ấm",
            "Hy vọng những thông tin này hữu ích. Mình có thể giúp gì thêm cho anh không?",
        ])
        text, fixes = humanize(reply, "mệt quá")
        self.assertEqual(text, "Đi ngủ sớm nhé, uống nước ấm")
        self.assertEqual(fixes, {"cliche", "list", "markdown"})

    def test_bubbles_survive_and_a_boilerplate_bubble_is_dropped(self):
        text, fixes = humanize("Dạ em nghe nè [SEND] Nếu anh cần thêm gì cứ nói em nhé! [SEND] anh ăn gì chưa?", "ừ")
        self.assertEqual(text, "Dạ em nghe nè [SEND] anh ăn gì chưa?")
        self.assertEqual(fixes, {"cliche"})

    def test_ai_disclaimer_clause_is_removed_keeping_the_rest(self):
        self.assertEqual(humanize("Là một mô hình ngôn ngữ, em không biết nữa.", "?")[0], "Em không biết nữa.")

    def test_long_answer_to_a_short_message_is_trimmed(self):
        long_reply = "Em vui lắm. " * 60
        text, fixes = humanize(long_reply, "hi")
        self.assertIn("length", fixes)
        self.assertLessEqual(len(text), 270)
        # Asking for an explanation earns the long answer.
        self.assertNotIn("length", humanize(long_reply, "giải thích tại sao trời xanh")[1])

    def test_lines_a_real_model_produced_are_cleaned(self):
        # Captured from nemotron-3.5-lightning in the live simulation.
        greeting = ("Chào buổi sáng! Tôi đang rất thoải mái và sẵn sàng. Chúc bạn có một ngày làm việc "
                    "sản xuất và ý nghĩa. Nếu có chuyện gì muốn nói hay cần giúp đỡ, cứ thoải mái hỏi nhé!")
        self.assertEqual(humanize(greeting, "hi"), ("Chào buổi sáng! Tôi đang rất thoải mái và sẵn sàng.", {"cliche"}))
        jargon = "Bún chả của anh thế nào? Tôi đang ở trạng thái sảng khoái (flow), sẵn sàng đón mọi chuyện!"
        self.assertEqual(humanize(jargon, "hi"), ("Bún chả của anh thế nào?", {"jargon"}))
        self.assertEqual(humanize("Em đang trong trạng thái hơi mệt nè anh", "hi")[1], set())

    def test_natural_chat_is_untouched_and_never_emptied(self):
        self.assertEqual(humanize("Hihi anh ngốc ghê", "haha"), ("Hihi anh ngốc ghê", set()))
        only_boilerplate = "Mình có thể giúp gì cho anh?"
        self.assertEqual(humanize(only_boilerplate, "x")[0], only_boilerplate)
        self.assertEqual(humanize("", "x"), ("", set()))


def _engine(llm_payload, tool_output=""):
    from tests.test_interaction_runtime_m0 import _PrivacyEgo

    ego = _PrivacyEgo()
    engine = SimpleNamespace(
        ego=ego,
        stm_lock=threading.Lock(),
        short_term_buffer=[],
        memory=SimpleNamespace(get_all=Mock(return_value=[])),
        world_graph=SimpleNamespace(query=Mock(return_value=[]), find_mentions=Mock(return_value=[])),
        memory_ops=SimpleNamespace(_apply_fog_masking=lambda t: t, update_or_add_memory=Mock(),
                                   save_short_term_memory=Mock(), sleep=Mock()),
        perception_ops=SimpleNamespace(get_sensory_summary=Mock(return_value="neutral")),
        skills=SimpleNamespace(get_prompt_instructions=Mock(return_value=""), execute=Mock(return_value=tool_output)),
        reader=SimpleNamespace(get_status=Mock(return_value="idle")),
        value_system=SimpleNamespace(get_moral_context=Mock(return_value="")),
        llm=SimpleNamespace(generate_json=Mock(return_value=(llm_payload, 0.0))),
    )
    controller = InteractionController(engine)
    controller.compressor = SimpleNamespace(compress=Mock(return_value=[]))
    controller.reflex_gate = SimpleNamespace(evaluate_reflexes=Mock(return_value={"triggered": False}))
    return controller


_BASE = {"valence": 0.1, "arousal": 0.2, "importance": 0.5, "type": "episodic",
         "internal_monologue": "ổn", "thought": "ổn"}


class PipelineTests(unittest.TestCase):
    def test_llm_reply_is_humanized_before_commit(self):
        controller = _engine(dict(_BASE, action=None, response="Dạ nè! Mình có thể giúp gì thêm cho anh không?"))
        with patch("builtins.print"):
            result = controller.perceive_and_respond("ê", [])
        self.assertEqual(result["response"], "Dạ nè!")

    def test_tool_output_is_never_rewritten(self):
        tool_output = NL.join(["- dòng 1", "- dòng 2"])
        controller = _engine(dict(_BASE, action="probe|x", response=""), tool_output=tool_output)
        with patch("builtins.print"):
            result = controller.perceive_and_respond("tra giúp anh", [])
        self.assertEqual(result["response"], tool_output)


class VoiceRuleTests(unittest.TestCase):
    def test_pronouns_and_no_label_reading_in_reply_and_ping_prompts(self):
        import inspect

        from config import Config
        from core import prompts

        with patch.object(Config, "SELF_PRONOUN", "em"), patch.object(Config, "OWNER_PRONOUN", "anh"):
            rules = prompts.voice_rules()
        self.assertIn("xưng 'em' và gọi User là 'anh'", rules)
        self.assertIn("KHÔNG đọc lại tên nhãn", rules)
        self.assertIn("voice_rules()", inspect.getsource(prompts.get_perceive_prompt))
        ping = inspect.getsource(prompts.get_proactive_ping_prompt)
        self.assertIn("voice_rules()", ping)
        self.assertNotIn("giây rồi", ping)  # silence as a fuzzy duration, not seconds


class SimulationP4Tests(unittest.TestCase):
    def test_assistant_drift_never_reaches_the_owner(self):
        report = run_week(seed=7)
        self.assertGreater(report.assistant_injected, 0)
        self.assertEqual(report.assistant_phrase_rate, 0.0)


if __name__ == "__main__":
    unittest.main()
