import asyncio
import json
import time
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException
from pydantic import ValidationError

from config import Config
from core.engine.slm_core import SLMCore, SLMServiceError
from core.local_perception import LocalPerception
from core.server import gpu_service


class SLMRoutingTests(unittest.TestCase):
    def test_remote_mode_uses_injected_http_client(self):
        response = Mock()
        response.json.return_value = {"thought": "remote thought"}
        client = Mock()
        client.post.return_value = response

        core = SLMCore(
            mode="remote",
            service_url="http://gpu.internal/",
            http_client=client,
        )

        self.assertEqual(core.generate_thought("hello", 12), "remote thought")
        client.post.assert_called_once_with(
            "http://gpu.internal/generate",
            json={"prompt": "hello", "max_new_tokens": 12},
            timeout=20,
        )
        response.raise_for_status.assert_called_once_with()

    def test_remote_mode_rejects_invalid_payload(self):
        response = Mock()
        response.json.return_value = {"unexpected": "value"}
        client = Mock()
        client.post.return_value = response
        core = SLMCore(mode="remote", http_client=client)

        with self.assertRaises(SLMServiceError):
            core.generate_thought("hello")

    def test_native_mode_dispatch_never_uses_http_client(self):
        core = SLMCore.__new__(SLMCore)
        core.mode = "native"
        core._http_client = Mock()

        with patch.object(core, "_generate_native", return_value="native") as native:
            self.assertEqual(core.generate_thought("hello", 7), "native")

        native.assert_called_once_with("hello", 7)
        core._http_client.post.assert_not_called()

    def test_invalid_mode_is_rejected_before_native_imports(self):
        with self.assertRaises(ValueError):
            SLMCore(mode="automatic")  # type: ignore[arg-type]

    def test_native_mode_is_not_ready_when_checkpoint_is_missing(self):
        with (
            patch.object(Config, "SLM_MODEL_PATH", "missing-checkpoint.pth"),
            patch.object(Config, "SLM_MODEL_DIR", "missing-assets"),
            patch("core.engine.slm_core.os.path.isfile", return_value=False),
        ):
            core = SLMCore(mode="native")

        self.assertFalse(core.is_ready)
        self.assertIn("checkpoint not found", core.init_error)

    def test_native_mode_is_not_ready_when_vocabulary_is_missing(self):
        def only_checkpoint_exists(path):
            return path.endswith("checkpoint.pth")

        with (
            patch.object(Config, "SLM_MODEL_PATH", "checkpoint.pth"),
            patch.object(Config, "SLM_MODEL_DIR", "missing-assets"),
            patch(
                "core.engine.slm_core.os.path.isfile",
                side_effect=only_checkpoint_exists,
            ),
        ):
            core = SLMCore(mode="native")

        self.assertFalse(core.is_ready)
        self.assertIn("vocabulary not found", core.init_error)


class PerceptionRoutingTests(unittest.TestCase):
    def test_remote_mode_uses_injected_http_client(self):
        response = Mock()
        response.json.return_value = {
            "valence": 0.1,
            "arousal": 0.2,
            "importance": 0.3,
        }
        client = Mock()
        client.post.return_value = response
        perception = LocalPerception(
            mode="remote",
            service_url="http://gpu.internal/",
            http_client=client,
        )

        result = perception.analyze("hello")

        self.assertEqual(result["valence"], 0.1)
        client.post.assert_called_once_with(
            "http://gpu.internal/analyze",
            json={"text": "hello"},
            timeout=10,
        )

    def test_native_mode_never_uses_http_client(self):
        perception = LocalPerception.__new__(LocalPerception)
        perception.mode = "native"
        perception.sentiment_analyzer = Mock(
            return_value=[{"label": "LABEL_2", "score": 0.8}]
        )
        perception.init_error = None
        perception._http_client = Mock()

        result = perception.analyze("hello")

        self.assertAlmostEqual(result["valence"], 0.56)
        perception._http_client.post.assert_not_called()

    def test_native_mode_maps_published_semantic_labels(self):
        perception = LocalPerception.__new__(LocalPerception)
        perception.mode = "native"
        perception.sentiment_analyzer = Mock(
            return_value=[{"label": "negative", "score": 0.8}]
        )
        perception.init_error = None

        result = perception.analyze("bad")

        self.assertAlmostEqual(result["valence"], -0.56)
        self.assertEqual(result["raw_label"], "negative")

    def test_native_mode_rejects_unknown_label(self):
        perception = LocalPerception.__new__(LocalPerception)
        perception.mode = "native"
        perception.sentiment_analyzer = Mock(
            return_value=[{"label": "surprise", "score": 0.8}]
        )
        perception.init_error = None

        with self.assertRaisesRegex(Exception, "unknown label"):
            perception.analyze("unexpected")

    def test_remote_mode_rejects_out_of_range_payload(self):
        response = Mock()
        response.json.return_value = {
            "valence": 9.0,
            "arousal": 0.2,
            "importance": 0.3,
        }
        client = Mock()
        client.post.return_value = response
        perception = LocalPerception(mode="remote", http_client=client)

        self.assertEqual(
            perception.analyze("hello"),
            {"valence": 0.0, "arousal": 0.5, "importance": 0.5},
        )


class _FakePerception:
    def __init__(self, *, ready=True, error=None):
        self.is_ready = ready
        self.error = error
        self.calls = 0

    def analyze(self, text):
        self.calls += 1
        if self.error:
            raise self.error
        return {"valence": 0.0, "arousal": 0.3, "importance": 0.5}


class _FakeSLM:
    def __init__(self, *, ready=True, error=None):
        self.is_ready = ready
        self.error = error
        self.calls = 0

    def generate_thought(self, prompt, max_tokens):
        self.calls += 1
        if self.error:
            raise self.error
        return f"thought:{prompt}:{max_tokens}"


class GPUServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.original_perception = gpu_service._local_perception
        self.original_slm = gpu_service._slm_core
        gpu_service._perception_semaphore = asyncio.Semaphore(1)
        gpu_service._slm_semaphore = asyncio.Semaphore(1)

    async def asyncTearDown(self):
        gpu_service._local_perception = self.original_perception
        gpu_service._slm_core = self.original_slm

    async def test_startup_constructs_only_native_backends(self):
        fake_perception = _FakePerception()
        fake_slm = _FakeSLM()
        with (
            patch("core.local_perception.LocalPerception", return_value=fake_perception) as p,
            patch("core.engine.slm_core.SLMCore", return_value=fake_slm) as s,
            patch.object(Config, "SLM_ENABLED", True),
            patch("builtins.print"),
        ):
            await gpu_service.startup_event()

        p.assert_called_once_with(mode="native")
        s.assert_called_once_with(mode="native")

    async def test_live_does_not_depend_on_model_readiness(self):
        gpu_service._local_perception = None
        gpu_service._slm_core = None
        self.assertEqual(await gpu_service.live(), {"status": "alive"})

    async def test_ready_is_503_when_required_perception_is_unavailable(self):
        gpu_service._local_perception = _FakePerception(ready=False)
        gpu_service._slm_core = None
        with patch.object(Config, "SLM_ENABLED", False):
            response = await gpu_service.ready()

        self.assertEqual(response.status_code, 503)
        payload = json.loads(response.body)
        self.assertFalse(payload["ready"])
        self.assertFalse(payload["capabilities"]["slm"]["enabled"])

    async def test_ready_ignores_slm_when_capability_is_disabled(self):
        gpu_service._local_perception = _FakePerception()
        gpu_service._slm_core = None
        with patch.object(Config, "SLM_ENABLED", False):
            response = await gpu_service.ready()

        self.assertTrue(response["ready"])

    async def test_ready_requires_slm_when_capability_is_enabled(self):
        gpu_service._local_perception = _FakePerception()
        gpu_service._slm_core = _FakeSLM(ready=False)
        with patch.object(Config, "SLM_ENABLED", True):
            response = await gpu_service.ready()

        self.assertEqual(response.status_code, 503)

    async def test_inference_endpoints_use_ready_native_backends(self):
        perception = _FakePerception()
        slm = _FakeSLM()
        gpu_service._local_perception = perception
        gpu_service._slm_core = slm

        analysis = await gpu_service.analyze_sentiment(
            gpu_service.AnalyzeRequest(text="hello")
        )
        with patch.object(Config, "SLM_ENABLED", True):
            generated = await gpu_service.generate_thought(
                gpu_service.GenerateRequest(prompt="hello", max_new_tokens=9)
            )

        self.assertEqual(analysis["arousal"], 0.3)
        self.assertEqual(generated, {"thought": "thought:hello:9"})
        self.assertEqual(perception.calls, 1)
        self.assertEqual(slm.calls, 1)

    async def test_disabled_or_unready_inference_returns_503_without_calling_model(self):
        perception = _FakePerception(ready=False)
        slm = _FakeSLM()
        gpu_service._local_perception = perception
        gpu_service._slm_core = slm

        with self.assertRaises(HTTPException) as analyze_error:
            await gpu_service.analyze_sentiment(
                gpu_service.AnalyzeRequest(text="hello")
            )
        with patch.object(Config, "SLM_ENABLED", False):
            with self.assertRaises(HTTPException) as generate_error:
                await gpu_service.generate_thought(
                    gpu_service.GenerateRequest(prompt="hello")
                )

        self.assertEqual(analyze_error.exception.status_code, 503)
        self.assertEqual(generate_error.exception.status_code, 503)
        self.assertEqual(perception.calls, 0)
        self.assertEqual(slm.calls, 0)

    async def test_internal_exception_message_is_not_exposed(self):
        gpu_service._local_perception = _FakePerception(
            error=RuntimeError("secret native detail")
        )

        with self.assertRaises(HTTPException) as caught:
            await gpu_service.analyze_sentiment(
                gpu_service.AnalyzeRequest(text="hello")
            )

        self.assertEqual(caught.exception.status_code, 500)
        self.assertNotIn("secret", str(caught.exception.detail))

    async def test_perception_requests_are_serialized(self):
        class TrackingPerception:
            is_ready = True

            def __init__(self):
                self.active = 0
                self.max_active = 0

            def analyze(self, text):
                self.active += 1
                self.max_active = max(self.max_active, self.active)
                time.sleep(0.02)
                self.active -= 1
                return {"valence": 0.0, "arousal": 0.3, "importance": 0.5}

        perception = TrackingPerception()
        gpu_service._local_perception = perception
        await asyncio.gather(
            gpu_service.analyze_sentiment(gpu_service.AnalyzeRequest(text="one")),
            gpu_service.analyze_sentiment(gpu_service.AnalyzeRequest(text="two")),
        )

        self.assertEqual(perception.max_active, 1)

    def test_request_bounds_are_enforced(self):
        with self.assertRaises(ValidationError):
            gpu_service.GenerateRequest(prompt="", max_new_tokens=0)
        with self.assertRaises(ValidationError):
            gpu_service.GenerateRequest(prompt="ok", max_new_tokens=513)
        with self.assertRaises(ValidationError):
            gpu_service.AnalyzeRequest(text="x" * 20_001)


if __name__ == "__main__":
    unittest.main()
