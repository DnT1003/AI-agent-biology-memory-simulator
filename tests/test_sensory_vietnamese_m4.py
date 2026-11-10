import math
import unittest
from unittest.mock import Mock, patch

from config import Config
from core.engine.sensory_preprocessor import SensoryPreprocessor
from core.local_perception import LocalPerception


def _vector(text, context=None):
    return SensoryPreprocessor().evaluate_input(text, context)["vector"]


class SensoryValenceTests(unittest.TestCase):
    def test_valence_is_taken_from_perception_context(self):
        self.assertEqual(_vector("xin chào", {"valence": -0.56})["valence"], -0.56)

    def test_missing_or_invalid_valence_is_neutral(self):
        for context in (None, {}, {"valence": math.nan}, {"valence": True}, {"valence": "0.9"}):
            self.assertEqual(_vector("xin chào", context)["valence"], 0.0, context)

    def test_valence_is_clamped(self):
        self.assertEqual(_vector("xin chào", {"valence": 3.0})["valence"], 1.0)

    def test_strong_valence_raises_arousal(self):
        calm = _vector("tao ghét mày", {"valence": 0.0})["arousal"]
        upset = _vector("tao ghét mày", {"valence": -0.7})["arousal"]
        self.assertAlmostEqual(upset - calm, 0.35, places=3)


class SensoryVietnameseCueTests(unittest.TestCase):
    def test_vietnamese_uppercase_with_diacritics_counts(self):
        text = "ĐỪNG ĐỘNG VÀO"
        expected = sum(1 for ch in text if ch.isupper()) / (len(text) + 1) * 0.5
        self.assertAlmostEqual(_vector(text)["arousal"], round(expected, 3))
        self.assertGreater(_vector(text)["arousal"], 0.35)

    def test_vietnamese_urgency(self):
        self.assertEqual(_vector("làm ngay lập tức")["urgency"], 0.6)
        self.assertEqual(_vector("hôm nay trời đẹp")["urgency"], 0.0)

    def test_vietnamese_certainty(self):
        self.assertEqual(_vector("có lẽ mai trời mưa")["certainty"], 0.2)
        self.assertEqual(_vector("chắc chắn là vậy")["certainty"], 0.8)

    def test_vietnamese_dominance(self):
        self.assertEqual(_vector("hãy kể chuyện cho tôi")["dominance"], 0.7)
        self.assertEqual(_vector("bạn khỏe không?")["dominance"], 0.4)

    def test_keywords_do_not_match_inside_words(self):
        # "ngay" must not fire inside "ngayngắn"-style compounds
        self.assertEqual(_vector("ngayngắn")["urgency"], 0.0)

    def test_english_cues_still_work(self):
        self.assertEqual(_vector("do it now")["urgency"], 0.6)
        self.assertEqual(_vector("do it now")["dominance"], 0.7)


class LocalPerceptionLabelTests(unittest.TestCase):
    def _native(self, label, score=0.8):
        perception = LocalPerception.__new__(LocalPerception)
        perception.mode = "native"
        perception.init_error = None
        perception.sentiment_analyzer = Mock(return_value=[{"label": label, "score": score}])
        return perception.analyze("x")

    def test_vietnamese_model_short_labels(self):
        self.assertAlmostEqual(self._native("NEG")["valence"], -0.56)
        self.assertAlmostEqual(self._native("POS")["valence"], 0.56)
        self.assertEqual(self._native("NEU")["valence"], 0.0)

    def test_model_name_defaults_to_config(self):
        with patch.object(Config, "LOCAL_PERCEPTION_MODEL", "org/custom-model"):
            perception = LocalPerception(mode="remote", service_auth_token="")
        self.assertEqual(perception.model_name, "org/custom-model")

    def test_explicit_model_name_wins(self):
        perception = LocalPerception("org/explicit", mode="remote", service_auth_token="")
        self.assertEqual(perception.model_name, "org/explicit")


class InputStressTests(unittest.TestCase):
    def _planned_stress(self, sensory_vector):
        import threading
        from types import SimpleNamespace
        from core.engine.interaction import InteractionController

        controller = InteractionController.__new__(InteractionController)
        controller.engine = SimpleNamespace(ego=SimpleNamespace(
            lock=threading.Lock(), social_need=0.5, stress=0.1, mood=0.0,
            vocabulary=[], integrity=1.0, is_identity_crisis=False,
        ))
        planned, _ = controller._plan_input_ego_updates(
            "xin chào", sensory_vector, {}, private_ephemeral=False
        )
        return planned.get("stress", 0.1)

    def test_positive_arousal_does_not_raise_stress(self):
        self.assertEqual(self._planned_stress({"valence": 0.7, "arousal": 0.6, "urgency": 0.0}), 0.1)

    def test_negative_arousal_raises_stress(self):
        self.assertAlmostEqual(self._planned_stress({"valence": -0.7, "arousal": 0.6, "urgency": 0.0}), 0.22)

    def test_urgency_raises_stress_regardless_of_valence(self):
        self.assertAlmostEqual(self._planned_stress({"valence": 0.7, "arousal": 0.6, "urgency": 0.6}), 0.28)


if __name__ == "__main__":
    unittest.main()
