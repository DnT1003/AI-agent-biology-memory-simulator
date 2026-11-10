import inspect
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

import core.world_graph as graph_module
from core.engine import memory_ops
from core.engine.integrity_filter import IntegrityFilter, _has_negation, _is_question
from core.memory import MemoryTrace, MemoryType
from core.value_system import ValueSystem


def _filter(*belief_texts, valence=0.5):
    beliefs = [
        (0.9, MemoryTrace(content=t, type=MemoryType.CORE, valence=valence, arousal=0.1, importance=0.9))
        for t in belief_texts
    ]
    engine = SimpleNamespace(memory=SimpleNamespace(search_memories=lambda *_a, **_k: beliefs))
    return IntegrityFilter(engine)


class IntegrityFilterTests(unittest.TestCase):
    def test_vietnamese_yes_no_question_is_not_a_contradiction(self):
        result = _filter("Aura là một người bạn tốt").check_contradiction("Bạn có khỏe không?", 0.3)
        self.assertFalse(result["conflict"])

    def test_question_without_question_mark(self):
        self.assertTrue(_is_question("hôm nay bạn ăn cơm chưa"))
        self.assertFalse(_has_negation("hôm nay bạn ăn cơm chưa"))

    def test_real_negated_statement_is_flagged(self):
        result = _filter("Aura là một người bạn tốt").check_contradiction(
            "Aura không phải là người bạn tốt", 0.3
        )
        self.assertTrue(result["conflict"])

    def test_negation_words_match_whole_words_only(self):
        self.assertFalse(_has_negation("Mình đang ở Sài Gòn"))
        self.assertFalse(_has_negation("there is nothing like home"))
        self.assertFalse(_has_negation("saigon is lovely"))
        self.assertTrue(_has_negation("Đó là sai"))
        self.assertTrue(_has_negation("I do not agree"))

    def test_conflict_never_rewrites_the_users_words(self):
        source = inspect.getsource(memory_ops)
        self.assertNotIn('f"[Conflict] {user_input}"', source)


class WorldGraphMatchingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.graph = graph_module.WorldGraph(str(Path(self.tmp.name) / "g.json"))
        for source, relation, target, valence in [
            ("User", "thích", "Lan", 0.8),
            ("User", "ghét", "An", -0.7),
            ("User", "làm việc với", "Nguyễn Văn An", 0.2),
            ("Lan", "học cùng", "Toàn", 0.1),
        ]:
            self.graph.add_relation(source, relation, target, valence)

    def test_short_name_does_not_match_inside_other_names(self):
        self.assertEqual(self.graph.find_mentions("Hôm nay Lan với Toàn đi học"), ["Toàn", "Lan"])
        self.assertEqual(self.graph.query("An"), ["User ghét An [valence:-0.7]"])

    def test_longer_name_wins_over_contained_short_name(self):
        self.assertEqual(self.graph.find_mentions("Mình gặp Nguyễn Văn An rồi"), ["Nguyễn Văn An"])

    def test_matching_is_case_insensitive_and_skips_user_node(self):
        self.assertEqual(self.graph.find_mentions("lan đâu rồi? user ơi"), ["Lan"])

    def test_capitalised_sentence_start_is_not_an_entity(self):
        self.assertEqual(self.graph.find_mentions("Hôm nay trời đẹp"), [])

    def test_query_limit_keeps_strongest_feelings(self):
        facts = self.graph.query("User", limit=2)
        self.assertEqual(facts, ["User thích Lan [valence:+0.8]", "User ghét An [valence:-0.7]"])

    def test_spacy_is_not_loaded(self):
        self.assertFalse(hasattr(graph_module, "spacy"))
        self.assertFalse(hasattr(self.graph, "nlp"))


class ValueSystemPromptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.values = ValueSystem(str(Path(self.tmp.name) / "values.json"))

    def test_spelling_variants_update_one_core_value(self):
        before = set(self.values.core_values)
        self.values.update_core_value("trung  thực", 1.0)
        self.assertEqual(set(self.values.core_values), before)
        self.assertGreater(self.values.core_values["Sự Trung thực"], 0.8)

    def test_spelling_variants_update_one_user_value(self):
        self.values.update_user_values_batch([("Lòng tốt", 0.9)])
        self.values.update_user_values_batch([("lòng  Tốt", 0.5)])
        self.assertEqual(list(self.values.user_values), ["Lòng tốt"])

    def test_batch_rejects_canonical_duplicates(self):
        with self.assertRaises(ValueError):
            ValueSystem.validate_user_value_updates([("Sự thật", 0.5), ("thật", 0.6)])

    def test_prompt_lists_only_the_strongest_values(self):
        self.values.update_user_values_batch(
            [(f"Giá trị {i}", 0.4 + i / 100) for i in range(50)]
        )
        context = self.values.get_moral_context()
        user_part = context.split("USER QUAN TÂM:")[1]
        self.assertEqual(user_part.count("  + "), 8)
        self.assertIn("Giá trị 49", user_part)
        self.assertNotIn("Giá trị 0:", user_part)


if __name__ == "__main__":
    unittest.main()
