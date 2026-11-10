import asyncio
import json
import os
import threading
import unittest
import warnings
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

warnings.filterwarnings(
    "ignore",
    message=r"Using `httpx` with `starlette\.testclient` is deprecated.*",
)

from fastapi.testclient import TestClient

from core import identity_drift
from core.chat_spool import ChatSpool, ChatSpoolError
from core.engine.autonomous import AutonomousController
from core.engine.interaction import InteractionController
from core.engine.lingering_thought import LingeringThought
from core.engine.memory_ops import MemoryOperationsController
from core.message_bubbles import (
    MAX_TYPING_DELAY,
    MIN_TYPING_DELAY,
    flatten_bubbles,
    split_bubbles,
    typing_delay,
)
from dashboard import server as dashboard_server


class _FixedRng:
    def __init__(self, value):
        self.value = value

    def random(self):
        return self.value

    def uniform(self, low, high):
        return low


class BubbleTests(unittest.TestCase):
    def test_split_tolerates_llm_tag_variants(self):
        text = "ơ [SEND] thật hả [ send ]  [Send]trời ơi"
        self.assertEqual(split_bubbles(text), ["ơ", "thật hả", "trời ơi"])
        self.assertEqual(flatten_bubbles(text), "ơ\nthật hả\ntrời ơi")

    def test_plain_text_is_one_bubble(self):
        self.assertEqual(split_bubbles("chào anh"), ["chào anh"])
        self.assertEqual(split_bubbles("  [SEND] "), [])

    def test_typing_delay_is_bounded_and_slower_when_tired(self):
        rng = _FixedRng(0.0)
        chunk = "x" * 60
        rested = typing_delay(chunk, fatigue=0.0, rng=rng)
        tired = typing_delay(chunk, fatigue=1.0, rng=rng)
        self.assertGreater(tired, rested)
        self.assertEqual(typing_delay("x" * 5000, rng=rng), MAX_TYPING_DELAY)
        self.assertEqual(typing_delay("", rng=rng), MIN_TYPING_DELAY)


class ProactiveSpoolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.spool = ChatSpool(Path(self.tmp.name) / "proactive", "response", lease_seconds=60)

    def tearDown(self):
        self.tmp.cleanup()

    def test_proactive_message_is_claimable_without_knowing_its_id(self):
        published = self.spool.publish_proactive("anh ơi, em nhớ anh")
        claims = self.spool.claim(limit=10)
        self.assertEqual([c.envelope.id for c in claims], [published.message_id])
        self.assertEqual(claims[0].envelope.role, "aura")
        self.assertTrue(self.spool.ack(claims[0].receipt))
        self.assertEqual(self.spool.stats()["processing"], 0)

    def test_request_spool_cannot_publish_proactive(self):
        requests = ChatSpool(Path(self.tmp.name) / "req", "request")
        with self.assertRaises(ChatSpoolError):
            requests.publish_proactive("x")


class DashboardProactiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        root = Path(self.tmp.name)
        self.requests = ChatSpool(root / "chat", "request", lease_seconds=60)
        self.responses = ChatSpool(root / "chat", "response", lease_seconds=60)
        self.proactive = ChatSpool(root / "proactive", "response", lease_seconds=60)
        self.token = "b" * 32
        self.patches = [
            patch.object(dashboard_server, "_get_chat_spools", return_value=(self.requests, self.responses)),
            patch.object(dashboard_server, "_get_proactive_spool", return_value=self.proactive),
            patch.object(dashboard_server.Config, "DASHBOARD_AUTH_TOKEN", self.token),
        ]
        for p in self.patches:
            p.start()
        self.client = TestClient(
            dashboard_server.app, headers={"Authorization": f"Bearer {self.token}"}
        )

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def test_poll_delivers_and_acks_proactive_messages(self):
        published = self.proactive.publish_proactive("em đây [SEND] nhớ anh")
        result = self.client.get("/api/chat", params={"proactive": "1"})
        self.assertEqual(result.status_code, 200)
        messages = result.json()["messages"]
        self.assertEqual([m["id"] for m in messages], [published.message_id])

        ack = self.client.post("/api/chat/ack", json={"receipts": [messages[0]["receipt"]]})
        self.assertEqual(ack.json(), {"acked": [messages[0]["receipt"]], "missing": 0})
        self.assertEqual(self.proactive.stats()["processing"], 0)

    def test_poll_without_flag_keeps_the_old_contract(self):
        self.proactive.publish_proactive("không ai hỏi")
        result = self.client.get("/api/chat")
        self.assertEqual(result.json(), {"messages": [], "terminal": []})
        self.assertEqual(self.proactive.stats()["pending"], 1)

    def test_replies_and_proactive_messages_arrive_together(self):
        request_id = self.requests.enqueue_request("hi").message_id
        self.responses.publish_response(request_id, "reply")
        self.proactive.publish_proactive("ping")
        result = self.client.get("/api/chat", params={"proactive": "1", "id": request_id})
        contents = sorted(m["content"] for m in result.json()["messages"])
        self.assertEqual(contents, ["ping", "reply"])

    def test_dashboard_ui_polls_proactive_and_renders_bubbles(self):
        html = dashboard_server.DASHBOARD_FILE.read_text(encoding="utf-8")
        self.assertIn("params.append('proactive', '1')", html)
        self.assertIn("appendBubbles(msg.role, msg.content)", html)
        self.assertNotIn("if(requestedIds.length === 0) return;", html)


class _FakeTyping:
    def __init__(self, log):
        self.log = log

    async def __aenter__(self):
        self.log.append("typing")

    async def __aexit__(self, *exc):
        return False


class _FakeChannel:
    def __init__(self):
        self.log = []
        self.done = threading.Event()
        self.expected = 0

    def typing(self):
        return _FakeTyping(self.log)

    async def send(self, text):
        self.log.append(text)
        if sum(1 for item in self.log if item != "typing") >= self.expected:
            self.done.set()


class DiscordBubbleTests(unittest.TestCase):
    def _bridge(self, channel, loop):
        import sys

        # discord.py is optional in the unit-test environment; the bridge is
        # built without its constructor, so only the import must succeed.
        if "discord" not in sys.modules:
            sys.modules["discord"] = SimpleNamespace(
                Intents=SimpleNamespace(default=lambda: None),
                Client=object,
                # Same lookup semantics as discord.utils.get, in case another
                # test module reuses this stub.
                utils=SimpleNamespace(get=lambda items, **kw: next(
                    (i for i in items if all(getattr(i, k, None) == v for k, v in kw.items())),
                    None,
                )),
            )
        from core.discord_bridge import AuraDiscordBot

        bridge = AuraDiscordBot.__new__(AuraDiscordBot)
        bridge.target_channel = channel
        bridge._loop = loop
        bridge._outbound_lock = None
        bridge.client = SimpleNamespace(is_closed=lambda: False)
        return bridge

    def test_bubbles_are_sent_in_order_with_typing_between(self):
        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()
        try:
            channel = _FakeChannel()
            channel.expected = 3
            bridge = self._bridge(channel, loop)
            with patch("core.message_bubbles.typing_delay", return_value=0.0):
                self.assertTrue(bridge.send_bubbles("một [SEND] hai [SEND] ba"))
                self.assertTrue(channel.done.wait(2.0))
            self.assertEqual(channel.log, ["một", "typing", "hai", "typing", "ba"])
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(2.0)
            loop.close()

    def test_not_ready_bridge_reports_not_sent(self):
        bridge = self._bridge(None, None)
        with patch("core.discord_bridge.logger"):
            self.assertFalse(bridge.send_bubbles("xin chào"))


class ProactiveDeliveryTests(unittest.TestCase):
    def test_ping_reaches_discord_and_dashboard(self):
        with TemporaryDirectory() as tmp:
            bridge = Mock()
            engine = SimpleNamespace(
                discord_bridge=bridge, ego=SimpleNamespace(fatigue=0.2, stress=0.1)
            )
            controller = AutonomousController(engine)
            controller._proactive_spool = ChatSpool(Path(tmp), "response", lease_seconds=60)
            with patch("builtins.print") as printed:
                self.assertTrue(controller._deliver_proactive("ơ [SEND] anh đâu rồi", "Chủ động"))
            bridge.send_bubbles.assert_called_once()
            self.assertEqual(bridge.send_bubbles.call_args.args[0], "ơ [SEND] anh đâu rồi")
            claims = controller._proactive_spool.claim(limit=5)
            self.assertEqual([c.envelope.content for c in claims], ["ơ [SEND] anh đâu rồi"])
            console = " ".join(str(arg) for call in printed.call_args_list for arg in call.args)
            self.assertNotIn("[SEND]", console)

    def test_dashboard_failure_still_counts_console_delivery(self):
        engine = SimpleNamespace(discord_bridge=None, ego=SimpleNamespace())
        controller = AutonomousController(engine)
        controller._proactive_spool = Mock(publish_proactive=Mock(side_effect=ChatSpoolError("disk")))
        with patch("builtins.print"), patch("core.engine.autonomous.logger"):
            self.assertTrue(controller._deliver_proactive("chào", "Chủ động"))
            self.assertFalse(controller._deliver_proactive("  [SEND] ", "Chủ động"))


class InputArousalTests(unittest.TestCase):
    def test_uses_sensory_intensity(self):
        self.assertAlmostEqual(InteractionController._input_arousal({"arousal": 0.7}, {}), 0.7)

    def test_sentiment_arousal_only_counts_with_clear_valence(self):
        neutral = {"valence": 0.0, "arousal": 0.9}
        upset = {"valence": -0.6, "arousal": 0.8}
        self.assertAlmostEqual(InteractionController._input_arousal({"arousal": 0.1}, neutral), 0.1)
        self.assertAlmostEqual(InteractionController._input_arousal({"arousal": 0.1}, upset), 0.8)

    def test_garbage_is_ignored(self):
        self.assertEqual(
            InteractionController._input_arousal({"arousal": float("nan")}, {"valence": True}), 0.0
        )

    def test_interaction_no_longer_asks_llm_for_arousal(self):
        source = Path("core/engine/interaction.py").read_text(encoding="utf-8")
        self.assertNotIn("CHẤN ĐỘNG (arousal)", source)
        self.assertNotIn("ADHD/INTRUSIVE", source)


class MimicryTests(unittest.TestCase):
    def test_keeps_vietnamese_compound_words(self):
        phrases = InteractionController._mimicry_phrases("Hôm nay buồn cười quá, rảnh rỗi ghê")
        self.assertIn("buồn cười", phrases)
        self.assertIn("rảnh rỗi", phrases)
        self.assertNotIn("buồn", phrases)

    def test_drops_function_words_and_numbers(self):
        phrases = InteractionController._mimicry_phrases("anh đang ở nhà 123")
        self.assertEqual(phrases, [])

    def test_keeps_latin_slang(self):
        self.assertIn("chill", InteractionController._mimicry_phrases("tối nay chill thôi"))


class LingeringThoughtTests(unittest.TestCase):
    def test_fresh_thought_fades_and_surfaces_once(self):
        thought = LingeringThought()
        thought.set("chương 3 của Số đỏ", now=1000.0)
        fresh = thought.surface_probability(1000.0)
        later = thought.surface_probability(1000.0 + 3600)
        self.assertGreater(fresh, later)
        self.assertEqual(thought.maybe_surface(1000.0, rng=_FixedRng(0.0)), "chương 3 của Số đỏ")
        self.assertIsNone(thought.maybe_surface(1000.0, rng=_FixedRng(0.0)))

    def test_unlucky_roll_keeps_the_thought(self):
        thought = LingeringThought()
        thought.set("x", now=0.0)
        self.assertIsNone(thought.maybe_surface(0.0, rng=_FixedRng(0.99)))
        self.assertEqual(thought.maybe_surface(0.0, rng=_FixedRng(0.0)), "x")

    def test_old_thought_is_gone(self):
        thought = LingeringThought()
        thought.set("x", now=0.0)
        self.assertEqual(thought.surface_probability(3 * 3600), 0.0)
        self.assertIsNone(thought.maybe_surface(3 * 3600, rng=_FixedRng(0.0)))


class IdentityDriftTests(unittest.TestCase):
    def test_decisions(self):
        old = "Tôi là người bạn tò mò, hay đọc sách và quan tâm anh."
        revised = "Tôi là người bạn tò mò, hay đọc sách, quan tâm anh nhưng hơi nhạy cảm."
        drastic = "Mình chỉ là một cỗ máy lạnh lùng vô cảm."
        self.assertEqual(identity_drift.decide("", drastic, ""), (True, ""))
        self.assertEqual(identity_drift.decide(identity_drift.DEFAULT_INSIGHT, drastic, ""), (True, ""))
        self.assertEqual(identity_drift.decide(old, revised, ""), (True, ""))
        self.assertEqual(identity_drift.decide(old, drastic, ""), (False, drastic))
        self.assertEqual(identity_drift.decide(old, drastic + " Thật vậy.", drastic), (True, ""))

    def _controller(self, ego, insight):
        controller = object.__new__(MemoryOperationsController)
        controller.engine = SimpleNamespace(
            ego=ego,
            stm_lock=threading.Lock(),
            short_term_buffer=["one", "two", "three", "four"],
            value_system=SimpleNamespace(get_moral_context=Mock(return_value="")),
            llm=SimpleNamespace(generate_text=Mock(return_value=(json.dumps({
                "insight": insight, "actionable_lessons": [], "value_updates": [],
            }), 0.0))),
            memory=SimpleNamespace(add_memory=Mock()),
        )
        return controller

    def test_one_bad_evening_does_not_rewrite_identity(self):
        old = "Tôi là người bạn tò mò, hay đọc sách và quan tâm anh."
        drastic = "Mình chỉ là một cỗ máy lạnh lùng vô cảm."
        ego = SimpleNamespace(
            lock=threading.Lock(), evolved_insight=old, actionable_lessons=[],
            pending_identity_insight="",
        )
        cwd = os.getcwd()
        with TemporaryDirectory() as tmp:
            os.chdir(tmp)
            try:
                Path("identity.json").write_text(
                    json.dumps({"override_device_id": "dev-1"}), encoding="utf-8"
                )
                with patch("builtins.print"):
                    first = self._controller(ego, drastic)
                    first._identity_evolution_phase()
                    self.assertEqual(ego.evolved_insight, old)
                    self.assertEqual(ego.pending_identity_insight, drastic)
                    first.engine.memory.add_memory.assert_not_called()
                    prompt = first.engine.llm.generate_text.call_args.args[0]
                    self.assertIn(old, prompt)

                    # The next night (reflection runs at most once per night).
                    ego.last_identity_reflection = 0.0
                    second = self._controller(ego, drastic)
                    second._identity_evolution_phase()
                self.assertEqual(ego.evolved_insight, drastic)
                self.assertEqual(ego.pending_identity_insight, "")
                second.engine.memory.add_memory.assert_called_once()
                saved = json.loads(Path("identity.json").read_text(encoding="utf-8"))
                self.assertEqual(saved["override_device_id"], "dev-1")
                self.assertEqual(saved["evolved_insight"], drastic)
            finally:
                os.chdir(cwd)


if __name__ == "__main__":
    unittest.main()
