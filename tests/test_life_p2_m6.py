import asyncio
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from config import Config
from core.chat_spool import ChatSpool
from core.engine import sleep_cycle
from core.engine.autonomous import AutonomousController
from core.engine.interaction import InteractionController
from core.engine.life_log import (
    LifeLog,
    activity_prompt,
    late_reply_prompt,
    note_message_received,
)
from core.prompts import get_synthesize_reading_prompt
from core.sim_week import run_week


class ReadingReactionTests(unittest.TestCase):
    def test_prompt_asks_for_a_reaction_without_spoilers(self):
        prompt = get_synthesize_reading_prompt("[Sách]: Số đỏ\nXuân bước vào...")
        self.assertIn("CẢM NHẬN", prompt)
        self.assertIn("không đoán trước diễn biến sau", prompt)
        self.assertIn('"share"', prompt)

    def test_reaction_is_validated_and_clamped(self):
        validate = AutonomousController._validated_reading_reaction
        text, feeling, share = validate({"reflection": " Hay quá ", "feeling": 3, "share": "Kể anh nghe"})
        self.assertEqual((text, feeling, share), ("Hay quá", 1.0, "Kể anh nghe"))
        self.assertEqual(validate({"reflection": "x", "feeling": "rất"})[1], 0.1)
        with self.assertRaises(ValueError):
            validate({"feeling": 0.5})
        with self.assertRaises(ValueError):
            validate("not json")


class PeekTests(unittest.TestCase):
    def test_peek_does_not_claim(self):
        with TemporaryDirectory() as tmp:
            requests = ChatSpool(Path(tmp), "request", lease_seconds=60)
            first = requests.enqueue_request("một").message_id
            requests.enqueue_request("hai")
            self.assertEqual(requests.peek_next().id, first)
            self.assertEqual(requests.stats()["processing"], 0)
            self.assertEqual(requests.claim()[0].envelope.id, first)
            self.assertEqual(requests.peek_next().content, "hai")


def _asleep_ego():
    return SimpleNamespace(lock=threading.Lock(), asleep_until=time.time() + 3600,
                           asleep_since=time.time() - 3600, sleep_intervals=[], fatigue=0.0)


class DeferralTests(unittest.TestCase):
    def test_defer_rules(self):
        ego, now = _asleep_ego(), time.time()
        self.assertFalse(sleep_cycle.should_defer_message(ego, "ngủ chưa", now, enabled=False))
        self.assertTrue(sleep_cycle.should_defer_message(ego, "ngủ chưa", now, enabled=True))
        self.assertFalse(sleep_cycle.should_defer_message(ego, "dậy ngay, gấp lắm!!", now, enabled=True))
        awake = SimpleNamespace(asleep_until=0.0)
        self.assertFalse(sleep_cycle.should_defer_message(awake, "ngủ chưa", now, enabled=True))
        self.assertFalse(sleep_cycle.should_defer_message(None, "x", now, enabled=True))

    def test_discord_messages_wait_until_she_wakes(self):
        ego = _asleep_ego()
        controller = AutonomousController(SimpleNamespace(ego=ego))
        bridge = SimpleNamespace(aura_inbox=__import__("queue").Queue())
        bridge.aura_inbox.put({"message_id": "1", "content": "em ngủ chưa"})
        bridge.aura_inbox.put({"message_id": "2", "content": "gấp lắm, dậy ngay!!"})
        with patch.object(Config, "DEFER_REPLIES_WHILE_ASLEEP", True):
            first = controller._discord_batch(bridge)
            self.assertEqual([m["message_id"] for m in first], ["2"])
            ego.asleep_until = 0.0
            later = controller._discord_batch(bridge)
        self.assertEqual([m["message_id"] for m in later], ["1"])
        self.assertIn("received_at", later[0])

    def test_web_message_stays_pending_while_asleep(self):
        with TemporaryDirectory() as tmp:
            requests = ChatSpool(Path(tmp), "request", lease_seconds=60)
            responses = ChatSpool(Path(tmp), "response", lease_seconds=60)
            requests.enqueue_request("em ngủ chưa")
            engine = SimpleNamespace(ego=_asleep_ego(), submit_interaction=Mock())
            controller = AutonomousController(engine)
            controller._chat_spools = (requests, responses)
            controller._last_chat_recovery = time.monotonic()
            with patch.object(Config, "DEFER_REPLIES_WHILE_ASLEEP", True), patch("builtins.print"):
                handled = asyncio.run(controller._process_web_chat_once())
            self.assertFalse(handled)
            engine.submit_interaction.assert_not_called()
            self.assertEqual(requests.stats(), {"pending": 1, "processing": 0, "dead": 0})


class LateReplyAndActivityTests(unittest.TestCase):
    def _engine(self):
        return SimpleNamespace(life_log=LifeLog(), ego=SimpleNamespace(sleep_intervals=[]))

    def test_late_reply_names_only_real_reasons(self):
        engine = self._engine()
        sent = 1_000_000.0
        engine.ego.sleep_intervals = [(sent - 3600, sent + 6 * 3600)]
        note_message_received(engine, "r1", sent)
        prompt = late_reply_prompt(engine, "r1", sent + 7 * 3600)
        self.assertIn("đang ngủ", prompt)
        self.assertIn("khoảng 7 tiếng", prompt)
        self.assertEqual(late_reply_prompt(engine, "r1", sent + 7 * 3600), "")  # consumed

    def test_quick_reply_or_unknown_reason(self):
        engine = self._engine()
        note_message_received(engine, "r2", 1_000.0)
        self.assertEqual(late_reply_prompt(engine, "r2", 1_100.0), "")
        note_message_received(engine, "r3", 1_000.0)
        self.assertIn("đừng bịa lý do", late_reply_prompt(engine, "r3", 5_000.0))

    def test_activity_comes_from_the_diary(self):
        engine = self._engine()
        now = 2_000_000.0
        self.assertEqual(activity_prompt(engine, now), "")
        engine.life_log.add("wake", "thức dậy", now - 600)
        self.assertIn("vừa ngủ dậy", activity_prompt(engine, now))
        engine.life_log.add("read", "[Sách]: Số đỏ - Chương 2", now - 60)
        self.assertIn("vừa gấp sách", activity_prompt(engine, now))
        self.assertEqual(activity_prompt(engine, now + 3 * 3600), "")


class BoredomTests(unittest.TestCase):
    def _model(self):
        from tests.test_self_model_load_m23 import _new_self_model

        model = _new_self_model()
        model.mood_anchor = None
        return model

    def test_idle_awake_hours_get_boring_sleep_clears_it(self):
        model = self._model()
        with patch("core.self_model.time.time", return_value=1_000_000.0), patch("builtins.print"):
            model.apply_biological_decay(4 * 3600, idle_time=5 * 3600)
            bored = model.boredom
            model.asleep_until = 2_000_000.0
            model.apply_biological_decay(4 * 3600, idle_time=9 * 3600)
        self.assertGreater(bored, 0.3)
        self.assertLess(model.boredom, bored * 0.2)

    def test_conversation_relieves_boredom_unless_it_repeats(self):
        ego = SimpleNamespace(boredom=0.8)
        controller = InteractionController.__new__(InteractionController)
        controller.engine = SimpleNamespace(ego=ego)
        fresh = SimpleNamespace(last_recalled=0.0)
        controller._update_boredom([fresh], {"valence": 0.0})
        self.assertAlmostEqual(ego.boredom, 0.4)
        same = SimpleNamespace(last_recalled=time.time())
        controller._update_boredom([same], {"valence": 0.0})
        self.assertAlmostEqual(ego.boredom, 0.5)
        controller._update_boredom([same], {"valence": -0.8})  # venting is never boring
        self.assertAlmostEqual(ego.boredom, 0.25)


class SimulationP2Tests(unittest.TestCase):
    def test_night_message_wakes_her_by_default_but_waits_when_deferring(self):
        default = run_week(seed=7, days=7)
        deferring = run_week(seed=7, days=7, defer_replies=True)
        self.assertGreaterEqual(default.prompt_markers["VỪA BỊ ĐÁNH THỨC"], 1)
        self.assertEqual(deferring.prompt_markers["VỪA BỊ ĐÁNH THỨC"], 0)
        self.assertGreaterEqual(deferring.prompt_markers["[TRẢ LỜI MUỘN]"], 1)
        self.assertTrue(default.reading_feelings)
        self.assertGreater(default.boredom_max, 0.3)


if __name__ == "__main__":
    unittest.main()
