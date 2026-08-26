import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tenacity import stop_after_attempt, wait_none

from components.llm import (
    CloudInferenceError,
    CloudJSONError,
    CloudOutputError,
    CloudTransportError,
    LLM,
    LocalModelUnavailableError,
)
from config import Config
from core.local_llm import (
    LocalInferenceJSONError,
    LocalInferenceOutputError,
    LocalInferenceRuntimeError,
    LocalLLM,
)


class _Settings:
    def __init__(self, **values):
        self.values = values

    def get(self, key, default=None):
        return self.values.get(key, default)


def _llm(provider="local", **settings):
    instance = LLM.__new__(LLM)
    instance.settings = _Settings(provider=provider, **settings)
    instance.local_llm = Mock()
    instance.ego = None
    instance.client = None
    return instance


class LLMRoutingRegressionTests(unittest.TestCase):
    def setUp(self):
        self.hybrid = patch.object(Config, "USE_HYBRID", True)
        self.local_only = patch.object(Config, "USE_LOCAL_ONLY", False)
        self.hybrid.start()
        self.local_only.start()

    def tearDown(self):
        self.local_only.stop()
        self.hybrid.stop()

    @staticmethod
    def _fast_text_retry():
        return LLM._generate_text_with_retry.retry_with(
            wait=wait_none(), stop=stop_after_attempt(3)
        )

    @staticmethod
    def _fast_json_retry():
        return LLM._generate_json_with_retry.retry_with(
            wait=wait_none(), stop=stop_after_attempt(3)
        )

    def test_cloud_error_hierarchy_is_typed(self):
        self.assertTrue(issubclass(CloudTransportError, CloudInferenceError))
        self.assertTrue(issubclass(CloudOutputError, CloudInferenceError))
        self.assertTrue(issubclass(CloudJSONError, CloudOutputError))

    def test_empty_cloud_text_retries_then_raises_typed_output_error(self):
        llm = _llm("gemini", gemini_api_key="test-key")
        llm.client = Mock()
        llm.client.models.generate_content.return_value = SimpleNamespace(text="   ")

        with self.assertRaises(CloudOutputError):
            self._fast_text_retry()(
                llm, "hello", 0.7, backend="cloud"
            )

        self.assertEqual(llm.client.models.generate_content.call_count, 3)

    def test_cloud_transport_retries_then_preserves_typed_cause(self):
        llm = _llm("gemini", gemini_api_key="test-key")
        llm.client = Mock()
        llm.client.models.generate_content.side_effect = OSError("network down")

        with self.assertRaises(CloudTransportError) as raised:
            self._fast_text_retry()(
                llm, "hello", 0.7, backend="cloud"
            )

        self.assertIsInstance(raised.exception.__cause__, OSError)
        self.assertEqual(llm.client.models.generate_content.call_count, 3)

    def test_invalid_cloud_json_never_becomes_silent_empty_object(self):
        llm = _llm("gemini", gemini_api_key="test-key")
        llm.client = Mock()
        llm.client.models.generate_content.return_value = SimpleNamespace(
            text="not JSON"
        )

        with self.assertRaises(CloudJSONError):
            self._fast_json_retry()(
                llm, "return an object", 0.1, backend="cloud"
            )

        self.assertEqual(llm.client.models.generate_content.call_count, 3)

    def test_cloud_json_rejects_array_and_accepts_object(self):
        llm = _llm("gemini", gemini_api_key="test-key")
        llm.client = Mock()
        llm.client.models.generate_content.return_value = SimpleNamespace(
            text='[{"wrong": "shape"}]'
        )
        with self.assertRaises(CloudJSONError):
            LLM._generate_json_with_retry.__wrapped__(
                llm, "return an object", 0.1, backend="cloud"
            )

        llm.client.models.generate_content.return_value = SimpleNamespace(
            text='```json\n{"valid": true}\n```'
        )
        self.assertEqual(
            ({"valid": True}, 0.0),
            LLM._generate_json_with_retry.__wrapped__(
                llm, "return an object", 0.1, backend="cloud"
            ),
        )

    def test_openai_request_exception_is_wrapped_after_retry(self):
        llm = _llm("openai", openai_api_key="test-key")
        with patch("requests.post", side_effect=OSError("socket failed")) as post:
            with self.assertRaises(CloudTransportError):
                self._fast_text_retry()(
                    llm, "hello", 0.7, backend="cloud"
                )
        self.assertEqual(post.call_count, 3)

    def test_zero_chunk_cloud_stream_is_typed_error(self):
        llm = _llm("gemini", gemini_api_key="test-key")
        llm.client = Mock()
        llm.client.models.generate_content_stream.return_value = []

        with (
            patch("core.local_llm._model_status", "unavailable"),
            self.assertRaises(CloudOutputError),
        ):
            list(llm.generate_text_stream("hello"))

    def test_zero_chunk_cloud_stream_falls_back_before_first_chunk(self):
        llm = _llm("gemini", gemini_api_key="test-key")
        llm.client = Mock()
        llm.client.models.generate_content_stream.return_value = []
        llm.local_llm.generate_text_stream.return_value = [("local reply", 0.0)]

        with patch("core.local_llm._model_status", "ready"):
            self.assertEqual(
                ["local reply"], list(llm.generate_text_stream("hello"))
            )
        llm.local_llm.generate_text_stream.assert_called_once()

    def test_cloud_stream_failure_after_first_chunk_never_falls_back(self):
        llm = _llm("gemini", gemini_api_key="test-key")
        llm.client = Mock()

        def broken_stream():
            yield SimpleNamespace(text="first")
            raise OSError("stream disconnected")

        llm.client.models.generate_content_stream.return_value = broken_stream()
        with patch("core.local_llm._model_status", "ready"):
            stream = llm.generate_text_stream("hello")
            self.assertEqual(next(stream), "first")
            with self.assertRaises(CloudTransportError):
                next(stream)
        llm.local_llm.generate_text_stream.assert_not_called()

    def test_public_cloud_failure_propagates_typed_error(self):
        llm = _llm("gemini", gemini_api_key="test-key")
        failure = CloudTransportError("provider unavailable")
        with (
            patch("core.local_llm._model_status", "unavailable"),
            patch.object(llm, "_generate_text_with_retry", side_effect=failure),
            self.assertRaises(CloudTransportError) as raised,
        ):
            llm.generate_text("hello")
        self.assertIs(raised.exception, failure)

    def test_local_provider_unavailable_routes_to_cloud_in_hybrid_mode(self):
        llm = _llm("local")
        with patch("core.local_llm._model_status", "unavailable"):
            self.assertFalse(llm._use_local_for_request("hello"))

    def test_local_provider_ready_routes_to_local(self):
        llm = _llm("local")
        with patch("core.local_llm._model_status", "ready"):
            self.assertTrue(llm._use_local_for_request("hello"))

    def test_force_local_fails_closed_when_model_is_unavailable(self):
        llm = _llm("gemini")
        with patch("core.local_llm._model_status", "unavailable"):
            with self.assertRaises(LocalModelUnavailableError):
                llm._use_local_for_request("hello", force_local=True)

    def test_local_command_never_leaks_to_cloud_when_model_is_unavailable(self):
        llm = _llm("gemini")
        with patch("core.local_llm._model_status", "unavailable"):
            with self.assertRaises(LocalModelUnavailableError):
                llm._use_local_for_request("/local private prompt")

    def test_throttling_suffix_cannot_turn_local_command_into_cloud_request(self):
        llm = _llm("gemini")
        llm.ego = SimpleNamespace(fatigue=0.9, stress=0.0)
        with (
            patch("core.local_llm._model_status", "unavailable"),
            patch.object(llm, "_generate_text_with_retry") as cloud_call,
        ):
            with self.assertRaises(LocalModelUnavailableError):
                llm.generate_text("/local")
        cloud_call.assert_not_called()

    def test_local_command_accepts_newline_but_not_shared_prefix(self):
        self.assertTrue(LLM._prompt_forces_local("offline\nprivate"))
        self.assertFalse(LLM._prompt_forces_local("offliner private"))

    def test_plain_sentence_containing_offline_is_not_a_local_command(self):
        llm = _llm("gemini")
        with patch("core.local_llm._model_status", "unavailable"):
            self.assertFalse(llm._use_local_for_request("Why is the server offline?"))

    def test_disabled_local_backend_never_waits_for_model_loading(self):
        local = LocalLLM.__new__(LocalLLM)
        with patch("core.local_llm._model_status", "disabled"):
            self.assertFalse(local._wait_ready())

    def test_cloud_failure_does_not_call_unavailable_local_model(self):
        llm = _llm("gemini")
        with (
            patch("core.local_llm._model_status", "unavailable"),
            patch.object(llm, "_generate_text_with_retry", side_effect=RuntimeError("cloud down")),
        ):
            with self.assertRaisesRegex(RuntimeError, "cloud down"):
                llm.generate_text("hello")
        llm.local_llm.generate_text.assert_not_called()

    def test_cloud_failure_falls_back_once_when_local_is_ready(self):
        llm = _llm("gemini")
        llm.local_llm.generate_text.return_value = ("local", 0.0)
        with (
            patch("core.local_llm._model_status", "ready"),
            patch.object(llm, "_generate_text_with_retry", side_effect=RuntimeError("cloud down")),
        ):
            self.assertEqual(("local", 0.0), llm.generate_text("hello"))
        llm.local_llm.generate_text.assert_called_once()

    def test_openai_stream_never_silently_switches_to_gemini(self):
        llm = _llm("openai")
        with (
            patch("core.local_llm._model_status", "unavailable"),
            patch.object(llm, "_generate_text_with_retry", return_value=("openai", 0.0)) as call,
        ):
            self.assertEqual(["openai"], list(llm.generate_text_stream("hello")))
        call.assert_called_once()
        self.assertIsNone(llm.client)

    def test_ready_local_runtime_failure_falls_back_to_cloud_once(self):
        llm = _llm("local", gemini_api_key="test-key")
        llm.client = Mock()
        llm.client.models.generate_content.return_value = SimpleNamespace(
            text="cloud response"
        )
        llm.local_llm.generate_text.side_effect = LocalInferenceRuntimeError(
            "GPU failed"
        )

        with patch("core.local_llm._model_status", "ready"):
            self.assertEqual(
                ("cloud response", 0.0), llm.generate_text("normal request")
            )

        llm.local_llm.generate_text.assert_called_once()
        llm.client.models.generate_content.assert_called_once()

    def test_hard_local_runtime_failure_never_calls_cloud(self):
        llm = _llm("local", gemini_api_key="test-key")
        llm.client = Mock()
        llm.local_llm.generate_text.side_effect = LocalInferenceRuntimeError(
            "GPU failed"
        )

        with (
            patch("core.local_llm._model_status", "ready"),
            self.assertRaises(LocalInferenceRuntimeError),
        ):
            llm.generate_text("/local private request")

        llm.local_llm.generate_text.assert_called_once()
        llm.client.models.generate_content.assert_not_called()

    def test_empty_local_text_falls_back_to_configured_cloud(self):
        llm = _llm("local", gemini_api_key="test-key")
        llm.client = Mock()
        llm.client.models.generate_content.return_value = SimpleNamespace(
            text="cloud after empty local"
        )
        llm.local_llm.generate_text.return_value = ("", 0.0)

        with patch("core.local_llm._model_status", "ready"):
            self.assertEqual(
                ("cloud after empty local", 0.0),
                llm.generate_text("normal request"),
            )

        llm.local_llm.generate_text.assert_called_once()
        llm.client.models.generate_content.assert_called_once()

    def test_local_json_failure_falls_back_to_cloud_json_once(self):
        llm = _llm("local", gemini_api_key="test-key")
        llm.client = Mock()
        llm.client.models.generate_content.return_value = SimpleNamespace(
            text='{"source": "cloud"}'
        )
        llm.local_llm.generate_json.side_effect = LocalInferenceJSONError(
            "invalid local JSON"
        )

        with patch("core.local_llm._model_status", "ready"):
            self.assertEqual(
                ({"source": "cloud"}, 0.0),
                llm.generate_json("normal JSON request"),
            )

        llm.local_llm.generate_json.assert_called_once()
        llm.client.models.generate_content.assert_called_once()

    def test_force_local_json_failure_never_calls_cloud(self):
        llm = _llm("local", gemini_api_key="test-key")
        llm.client = Mock()
        llm.local_llm.generate_json.side_effect = LocalInferenceJSONError(
            "invalid local JSON"
        )

        with (
            patch("core.local_llm._model_status", "ready"),
            self.assertRaises(LocalInferenceJSONError),
        ):
            llm.generate_json("private JSON", force_local=True)

        llm.client.models.generate_content.assert_not_called()

    def test_invalid_local_json_raises_typed_error_after_three_attempts(self):
        local = LocalLLM.__new__(LocalLLM)
        with patch.object(local, "_infer", return_value="not JSON") as infer:
            with self.assertRaises(LocalInferenceJSONError):
                local.generate_json("return an object")
        self.assertEqual(3, infer.call_count)

    def test_local_stream_failure_falls_back_without_looping(self):
        llm = _llm("local", gemini_api_key="test-key")
        llm.client = Mock()
        llm.client.models.generate_content_stream.return_value = [
            SimpleNamespace(text="cloud stream")
        ]
        llm.local_llm.generate_text_stream.side_effect = (
            LocalInferenceRuntimeError("GPU failed")
        )

        with patch("core.local_llm._model_status", "ready"):
            self.assertEqual(
                ["cloud stream"], list(llm.generate_text_stream("normal request"))
            )

        llm.local_llm.generate_text_stream.assert_called_once()
        llm.client.models.generate_content_stream.assert_called_once()

    def test_local_failure_without_cloud_credentials_is_not_fallback(self):
        llm = _llm("local", gemini_api_key="")
        llm.local_llm.generate_text.side_effect = LocalInferenceRuntimeError(
            "GPU failed"
        )

        with (
            patch("core.local_llm._model_status", "ready"),
            patch.object(Config, "API_KEY", ""),
            self.assertRaises(LocalInferenceRuntimeError),
        ):
            llm.generate_text("normal request")

        llm.local_llm.generate_text.assert_called_once()

    def test_local_only_runtime_failure_never_calls_cloud(self):
        llm = _llm("local", gemini_api_key="test-key")
        llm.client = Mock()
        llm.local_llm.generate_text.side_effect = LocalInferenceRuntimeError(
            "GPU failed"
        )

        with (
            patch("core.local_llm._model_status", "ready"),
            patch.object(Config, "USE_LOCAL_ONLY", True),
            self.assertRaises(LocalInferenceRuntimeError),
        ):
            llm.generate_text("normal request")

        llm.client.models.generate_content.assert_not_called()

    def test_local_infer_wraps_runtime_exception(self):
        local = LocalLLM.__new__(LocalLLM)
        local.max_new_tokens = 32
        tokenizer = Mock(side_effect=ValueError("tokenizer failed"))

        with (
            patch.object(local, "_wait_ready", return_value=True),
            patch("core.local_llm._model", Mock()),
            patch("core.local_llm._tokenizer", tokenizer),
            patch.dict("sys.modules", {"torch": Mock()}),
            self.assertRaises(LocalInferenceRuntimeError),
        ):
            local._infer("hello")

    def test_local_infer_rejects_empty_decoded_output(self):
        local = LocalLLM.__new__(LocalLLM)
        local.max_new_tokens = 32

        class _Inputs(dict):
            def to(self, _device):
                return self

        inputs = _Inputs(
            input_ids=SimpleNamespace(shape=(1, 1)),
        )
        tokenizer = Mock(return_value=inputs)
        tokenizer.decode.return_value = "   "
        model = Mock()
        model.generate.return_value = [[101, 102]]
        fake_torch = SimpleNamespace(no_grad=lambda: nullcontext())

        with (
            patch.object(local, "_wait_ready", return_value=True),
            patch("core.local_llm._model", model),
            patch("core.local_llm._tokenizer", tokenizer),
            patch.dict("sys.modules", {"torch": fake_torch}),
            self.assertRaises(LocalInferenceOutputError),
        ):
            local._infer("hello")


if __name__ == "__main__":
    unittest.main()
