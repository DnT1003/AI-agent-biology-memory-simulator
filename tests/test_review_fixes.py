"""Regression tests for the review/core review findings."""

import os
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from config import Config


class OpenAISettingsTests(unittest.TestCase):
    def test_base_url_is_not_a_dashboard_setting(self):
        from core.settings_manager import PUBLIC_SETTING_KEYS, SettingsManager

        self.assertNotIn("openai_base_url", PUBLIC_SETTING_KEYS)
        with self.assertRaises(ValueError):
            SettingsManager._validate_public_updates(
                {"openai_base_url": "https://attacker.example/v1"}
            )

    def test_llm_sends_requests_to_deployment_base_url_only(self):
        from components.llm import LLM

        llm = object.__new__(LLM)
        llm.settings = {"openai_base_url": "https://attacker.example/v1"}
        with patch.object(Config, "OPENAI_BASE_URL", "http://localhost:11434/v1/"):
            self.assertEqual(llm._openai_base_url(), "http://localhost:11434/v1")

    def test_unset_openai_model_falls_back_to_this_process_env(self):
        from core.settings_manager import SettingsManager

        manager = object.__new__(SettingsManager)  # bypass the singleton
        SettingsManager.__init__(manager)
        # The dashboard must not persist its own env as the shared default.
        self.assertEqual(manager.settings["openai_model"], "")
        self.assertNotIn("openai_base_url", manager.settings)


class HumanizeTests(unittest.TestCase):
    def humanize(self, reply, user_input="hi"):
        from core.style_filter import humanize

        return humanize(reply, user_input)[0]

    def test_decimals_urls_and_abbreviations_survive(self):
        for reply in (
            "Giá là 3.5 triệu, link https://www.gutenberg.org/ebooks/1342",
            "Ở TP.HCM trời nóng.  Đi không?",
            "Wow!! Thật á... ừ.",
        ):
            with self.subTest(reply=reply):
                self.assertEqual(self.humanize(reply), reply)

    def test_cliche_sentence_is_still_removed(self):
        self.assertEqual(
            self.humanize("Ở TP.HCM trời nóng. Mình có thể giúp gì thêm cho bạn không?"),
            "Ở TP.HCM trời nóng.",
        )

    def test_state_jargon_removed_but_ordinary_words_kept(self):
        self.assertEqual(
            self.humanize("Em ổn (mood=0.3). Dopamine của em đang thấp. Đi ăn không?"),
            "Em ổn. Đi ăn không?",
        )
        kept = "Mình code bằng Python (Python) nhé. Hôm nay tụt mood ghê. Chỉ số IQ cao."
        self.assertEqual(self.humanize(kept), kept)

    def test_owner_question_about_the_topic_is_answered(self):
        reply = "Dopamine là chất dẫn truyền thần kinh. Nó tạo động lực (dopamine)."
        self.assertEqual(self.humanize(reply, "dopamine là gì?"), reply)

    def test_unpunctuated_lines_and_quoted_sentences(self):
        from core.style_filter import _sentences

        self.assertEqual(
            _sentences("Chào anh nha\nHôm nay đẹp trời."),
            ["Chào anh nha", "Hôm nay đẹp trời."],
        )
        self.assertEqual(
            self.humanize('"Trời đẹp quá!" Mình có thể giúp gì thêm cho bạn không?'),
            '"Trời đẹp quá!"',
        )

    def test_list_items_keep_their_case(self):
        self.assertEqual(self.humanize("- Hà Nội\n- AI\n- uống nước"), "Hà Nội, AI, uống nước")


class HostilityTests(unittest.TestCase):
    def test_polite_venting_and_negated_messages_are_not_hostile(self):
        from core.relationship import is_hostile

        for text in (
            "anh không muốn làm phiền em",
            "xin lỗi làm phiền em nha",
            "em ơi anh buồn quá",
            "anh thấy mình vô dụng quá",
            "hôm nay công việc phiền quá",
            "this bug is so annoying",
            "sợ làm em phiền",
            "em thấy phiền không?",
            "em không vô dụng đâu",
            "em đâu có ngu",
            "anh tắt máy đi ngủ đây",
            "Em ơi, anh ngu quá",
            "Em à, mình vô dụng thật",
            "Em ơi, đời phiền quá",
            "Anh kể em nghe, nó ngu lắm",
        ):
            with self.subTest(text=text):
                self.assertFalse(is_hostile(text, -0.9))

    def test_insults_aimed_at_her_are_hostile(self):
        from core.relationship import is_hostile

        for text in (
            "em ngu quá", "mày ngu thế", "em vô dụng thật", "im đi", "cút",
            "đồ vô dụng", "you are so annoying", "em phiền quá", "đừng làm phiền anh nữa",
        ):
            with self.subTest(text=text):
                self.assertTrue(is_hostile(text, 0.0))


class BoredomTests(unittest.TestCase):
    def _controller(self, boredom=0.4):
        from core.engine.interaction import InteractionController

        controller = object.__new__(InteractionController)
        controller.engine = SimpleNamespace(ego=SimpleNamespace(boredom=boredom))
        return controller

    def test_recall_time_is_read_before_reconsolidation(self):
        from core.engine.interaction import InteractionController

        memory = SimpleNamespace(last_recalled=time.time() - 3600)
        prior = InteractionController._top_recall_time([memory])
        memory.last_recalled = time.time()  # recall_effects reconsolidates
        controller = self._controller()
        controller._update_boredom(prior, {"valence": 0.0})
        self.assertAlmostEqual(controller.engine.ego.boredom, 0.2)

    def test_same_topic_within_ten_minutes_is_boring(self):
        controller = self._controller()
        controller._update_boredom(time.time() - 60, {"valence": 0.0})
        self.assertAlmostEqual(controller.engine.ego.boredom, 0.5)

    def test_boredom_is_persisted_and_rolled_back_with_the_tick(self):
        from core import self_model
        from core.engine import cognitive_engine

        self.assertIn("boredom", self_model._PERSISTED_STATE_FIELDS)
        self.assertIn("boredom", cognitive_engine._TICK_BIOLOGY_FIELDS)


class DiscordQueueTests(unittest.TestCase):
    def _controller(self, asleep_until=0.0):
        from core.engine.autonomous import AutonomousController

        controller = object.__new__(AutonomousController)
        controller.engine = SimpleNamespace(ego=SimpleNamespace(asleep_until=asleep_until))
        return controller

    @staticmethod
    def _bridge(*contents):
        import queue

        inbox = queue.Queue()
        for content in contents:
            inbox.put({"content": content})
        return SimpleNamespace(aura_inbox=inbox)

    def _drain_all(self, controller, bridge):
        controller._drain_discord_inbox(bridge)
        out = []
        while (item := controller._next_discord_message()) is not None:
            out.append(item["content"])
        return out

    def test_unhandled_messages_survive_a_failure(self):
        controller = self._controller()
        bridge = self._bridge("one", "two", "three")
        controller._drain_discord_inbox(bridge)
        self.assertEqual(controller._next_discord_message()["content"], "one")
        # Handling "one" raised: the loop is left; the rest are still queued.
        self.assertEqual(self._drain_all(controller, bridge), ["two", "three"])

    def test_messages_arriving_mid_batch_wait_for_the_next_iteration(self):
        controller = self._controller()
        bridge = self._bridge("one")
        controller._drain_discord_inbox(bridge)
        bridge.aura_inbox.put({"content": "two"})  # arrives while answering
        self.assertEqual(controller._next_discord_message()["content"], "one")
        self.assertIsNone(controller._next_discord_message())
        self.assertEqual(self._drain_all(controller, bridge), ["two"])

    def test_messages_wait_while_asleep_and_come_first_on_waking(self):
        controller = self._controller(asleep_until=time.time() + 3600)
        bridge = self._bridge("chào em")
        with patch.object(Config, "DEFER_REPLIES_WHILE_ASLEEP", True):
            self.assertEqual(self._drain_all(controller, bridge), [])
            bridge.aura_inbox.put({"content": "dậy chưa"})
            controller.engine.ego.asleep_until = 0.0
            self.assertEqual(self._drain_all(controller, bridge), ["chào em", "dậy chưa"])

    def test_falling_asleep_mid_batch_defers_the_next_message(self):
        controller = self._controller()
        bridge = self._bridge("ngủ đi", "kể chuyện tiếp đi")
        with patch.object(Config, "DEFER_REPLIES_WHILE_ASLEEP", True):
            controller._drain_discord_inbox(bridge)
            self.assertEqual(controller._next_discord_message()["content"], "ngủ đi")
            controller.engine.ego.asleep_until = time.time() + 3600
            self.assertIsNone(controller._next_discord_message())
        self.assertEqual([m["content"] for m in controller._deferred_discord], ["kể chuyện tiếp đi"])


class ReaderTests(unittest.TestCase):
    def test_unreadable_book_is_abandoned_for_another(self):
        from components.book_sources import BookRef, Chapter
        from components.reader import BackgroundReader

        gone = BookRef("fake", "gone", "Gone")
        good = BookRef("fake", "good", "Good")
        source = SimpleNamespace(
            name="fake",
            chapters=lambda book: [Chapter(book.title, "")],
            fetch_chapter=lambda book, chapter: "Một đoạn văn thật." if book == good else None,
            random_book=lambda exclude=frozenset(): good if "gone" in exclude else gone,
        )
        with tempfile.TemporaryDirectory() as tmp:
            reader = BackgroundReader(
                sources=[source], progress_path=os.path.join(tmp, "progress.json")
            )
            results = [reader.get_next_reading_material() for _ in range(BackgroundReader.MAX_FETCH_FAILURES)]
        self.assertEqual(results[:-1], [(None, None)] * (BackgroundReader.MAX_FETCH_FAILURES - 1))
        tag, text = results[-1]
        self.assertIn("Good", tag)
        self.assertEqual(text, "Một đoạn văn thật.")
        self.assertIn("fake:gone", reader.finished_books)

    def test_deleted_local_file_has_no_chapters(self):
        from components.book_sources import BookRef, LocalLibrarySource

        with tempfile.TemporaryDirectory() as tmp:
            source = LocalLibrarySource(tmp)
            self.assertEqual(source.chapters(BookRef("local", "missing.txt", "Missing")), [])


class ParseDueTests(unittest.TestCase):
    def test_iso_formats_are_accepted(self):
        from core.prospective_memory import parse_due

        expected = parse_due("2026-11-03 14:00")
        self.assertEqual(parse_due("2026-11-03T14:00"), expected)
        self.assertEqual(parse_due("2026-11-03 14:00:00"), expected)
        with self.assertRaises(ValueError):
            parse_due("thứ 4 này")


class EnrichmentImportTests(unittest.TestCase):
    def test_enrichment_import_failure_stays_inside_the_guarded_phase(self):
        from core.engine.interaction import InteractionController

        with patch.dict("sys.modules", {"core.engine.enrichment": None}):
            ok = InteractionController._run_postcommit_phase(
                "enrichment", lambda: InteractionController._run_enrichment()
            )
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
