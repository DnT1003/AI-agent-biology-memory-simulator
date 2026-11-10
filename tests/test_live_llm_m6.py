import importlib.util
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core.sim_week import RateLimitedLLM, run_week

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "simulate_week_live.py"
_spec = importlib.util.spec_from_file_location("simulate_week_live", _SCRIPT)
live = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(live)


class _FakeOpenAI(BaseHTTPRequestHandler):
    """Minimal OpenAI-compatible server standing in for Ollama."""

    requests_seen = []

    def log_message(self, *args):
        pass

    def _send(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/v1/models":
            self._send({"data": [{"id": "fake-model"}]})
        else:
            self._send({"error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        request = json.loads(self.rfile.read(length))
        type(self).requests_seen.append((self.headers.get("Authorization"), request))
        prompt = request["messages"][-1]["content"]
        if "BẢN SẮC HIỆN TẠI" in prompt:
            content = json.dumps({"insight": "Tôi là người bạn tò mò và hay quan tâm.",
                                  "actionable_lessons": [], "value_updates": []}, ensure_ascii=False)
        elif "open_loops" in prompt:
            content = json.dumps({"relations": [], "values": [], "open_loops": [], "user_busy": None})
        elif "Aura vừa đọc xong" in prompt:
            content = json.dumps({"reflection": "Đoạn này hay.", "feeling": 0.3, "share": "Kể anh nghe nè"},
                                 ensure_ascii=False)
        elif request.get("response_format", {}).get("type") == "json_object":
            content = json.dumps({"response": "Dạ em đây, anh kể tiếp đi", "thought": "ổn",
                                  "valence": 0.2, "arousal": 0.2, "importance": 0.5,
                                  "type": "episodic", "internal_monologue": "ổn", "action": None},
                                 ensure_ascii=False)
        else:
            content = "Ừ, em nghe nè."
        self._send({"choices": [{"message": {"role": "assistant", "content": content}}]})


class LiveEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeOpenAI)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_address[1]}/v1"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        _FakeOpenAI.requests_seen.clear()

    def test_probe_lists_models_and_reports_a_dead_endpoint(self):
        self.assertEqual(live.probe(self.base_url, ""), (True, ["fake-model"]))
        ok, detail = live.probe("http://127.0.0.1:9/v1", "", timeout=2)
        self.assertFalse(ok)
        self.assertIn("Connect", detail)  # refused or timed out, depending on the firewall

    def test_project_llm_talks_to_a_local_openai_compatible_server(self):
        from components.llm import LLM
        from config import Config

        with patch.object(Config, "LOCAL_LLM_ENABLED", False):
            llm = LLM(ego=None)
        llm.settings = live._Settings({"provider": "openai", "openai_base_url": self.base_url,
                                       "openai_model": "fake-model", "openai_api_key": ""})
        payload, _ = llm.generate_json('Trả về JSON có "response"', bio_throttle=False)
        self.assertEqual(payload["response"], "Dạ em đây, anh kể tiếp đi")
        auth, request = _FakeOpenAI.requests_seen[-1]
        self.assertEqual(auth, "Bearer local")  # no key needed for a local server
        self.assertEqual(request["model"], "fake-model")
        self.assertNotIn("helpful assistant", request["messages"][0]["content"])

    def test_remote_endpoint_without_key_is_refused(self):
        from components.llm import LLM, LLMConfigurationError
        from config import Config

        with patch.object(Config, "LOCAL_LLM_ENABLED", False):
            llm = LLM(ego=None)
        llm.settings = live._Settings({"provider": "openai", "openai_base_url": "https://example.com/v1"})
        with self.assertRaises(LLMConfigurationError):
            llm.generate_json("x", bio_throttle=False)

    def test_simulated_day_runs_on_the_real_llm_path(self):
        factory = live.make_llm_factory(self.base_url, "fake-model", "", rpm=0)
        from config import Config

        with patch.object(Config, "LOCAL_LLM_ENABLED", Config.LOCAL_LLM_ENABLED):
            report = run_week(seed=7, days=1, llm_factory=factory)
        self.assertGreater(report.llm_calls, 0)
        self.assertEqual(report.llm_failures, 0)
        self.assertEqual(report.failed_turns, [])
        replies = [text for _, _, kind, text in report.aura_messages if kind == "reply"]
        self.assertIn("Dạ em đây, anh kể tiếp đi", replies)
        self.assertTrue(_FakeOpenAI.requests_seen)


class RateLimiterTests(unittest.TestCase):
    def _limited(self, inner, rpm=30.0):
        clock = SimpleNamespace(now=0.0)
        slept = []

        def sleep(seconds):
            slept.append(seconds)
            clock.now += seconds

        limiter = RateLimitedLLM(inner, rpm=rpm, retries=2, backoff_seconds=5.0,
                                 sleep=sleep, clock=lambda: clock.now)
        return limiter, slept

    def test_calls_are_spaced(self):
        inner = SimpleNamespace(generate_text=lambda p, *a, **k: ("ok", 0.0))
        limiter, slept = self._limited(inner, rpm=30.0)
        for _ in range(3):
            limiter.generate_text("x")
        self.assertEqual(slept, [2.0, 2.0])

    def test_rate_limit_errors_back_off_and_retry(self):
        calls = []

        def flaky(prompt, *a, **k):
            calls.append(prompt)
            if len(calls) < 3:
                raise RuntimeError("HTTP 429 Too Many Requests")
            return {"response": "ok"}, 0.0

        limiter, slept = self._limited(SimpleNamespace(generate_json=flaky), rpm=0)
        self.assertEqual(limiter.generate_json("x")[0]["response"], "ok")
        self.assertEqual(limiter.retried, 2)
        self.assertEqual(slept, [5.0, 10.0])

    def test_other_errors_are_not_retried(self):
        def broken(prompt, *a, **k):
            raise ValueError("bad prompt")

        limiter, _ = self._limited(SimpleNamespace(generate_json=broken), rpm=0)
        with self.assertRaises(ValueError):
            limiter.generate_json("x")
        self.assertEqual(limiter.retried, 0)


if __name__ == "__main__":
    unittest.main()
