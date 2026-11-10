# LLM Component wrapper cho Google GenAI
import contextvars
import functools
import json
import logging
import re
import time
import uuid
from typing import Any, Optional
from google import genai
from google.genai import types
from config import Config
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception
from core.local_llm import (
    LocalInferenceError,
    LocalInferenceJSONError,
    LocalInferenceOutputError,
    LocalInferenceRuntimeError,
    LocalLLM,
)
from core.event_journal import record_current_event

logger = logging.getLogger(__name__)


_ACTIVE_INFERENCE_OBSERVATION: contextvars.ContextVar[dict | None] = (
    contextvars.ContextVar("aura_llm_inference_observation", default=None)
)


def _record_observation(event_type: str, payload: dict, *, outcome: str) -> None:
    """Keep observability strictly fail-open at an inference boundary."""

    try:
        record_current_event(event_type, payload, outcome=outcome)
    except Exception:
        logger.warning("Unable to record inference event", exc_info=True)


def _positional_or_keyword(args, kwargs, name: str, index: int, default=None):
    if name in kwargs:
        return kwargs[name]
    if len(args) > index:
        return args[index]
    return default


def _safe_route_metadata(llm, model_override, backend: str | None) -> dict:
    """Read only non-secret routing labels without invoking routing again."""

    values = getattr(getattr(llm, "settings", None), "settings", None)
    if not isinstance(values, dict):
        values = getattr(getattr(llm, "settings", None), "values", None)
    if not isinstance(values, dict):
        values = {}

    provider = str(values.get("provider", "local")).strip().lower()
    if provider not in {"local", "gemini", "openai", "anthropic"}:
        provider = "unknown"

    metadata: dict[str, object] = {"provider": provider}
    if backend in {"local", "cloud"}:
        metadata["backend"] = backend

    model = model_override
    if not model:
        if backend == "local":
            model = values.get("local_model", getattr(Config, "LOCAL_MODEL_NAME", None))
        else:
            effective_provider = "gemini" if provider == "local" else provider
            model = values.get(f"{effective_provider}_model")
            if not model and effective_provider == "gemini":
                model = getattr(Config, "MODEL_NAME", None)
    if isinstance(model, str) and 0 < len(model) <= 256:
        metadata["model"] = model
    return metadata


def _set_inference_backend(backend: str, *, fallback: bool = False) -> None:
    observation = _ACTIVE_INFERENCE_OBSERVATION.get()
    if observation is None:
        return
    observation["backend"] = backend
    if fallback:
        observation["fallback_count"] += 1


def _observe_inference(kind: str, *, model_index: int, force_local_index: int):
    """Emit metadata-only events around a public non-streaming LLM call."""

    def decorate(method):
        @functools.wraps(method)
        def observed(self, *args, **kwargs):
            call_id = uuid.uuid4().hex
            started_at = time.monotonic()
            model_override = _positional_or_keyword(
                args, kwargs, "model_override", model_index
            )
            force_local = bool(
                _positional_or_keyword(
                    args, kwargs, "force_local", force_local_index, False
                )
            )
            initial_backend = (
                "local" if force_local or Config.USE_LOCAL_ONLY else None
            )
            observation = {
                "backend": initial_backend,
                "fallback_count": 0,
            }
            token = _ACTIVE_INFERENCE_OBSERVATION.set(observation)
            started_payload = {
                "call_id": call_id,
                "kind": kind,
                "force_local": force_local,
                **_safe_route_metadata(self, model_override, initial_backend),
            }
            _record_observation(
                "inference.started", started_payload, outcome="started"
            )
            try:
                result = method(self, *args, **kwargs)
            except BaseException as error:
                finished_payload = {
                    "call_id": call_id,
                    "kind": kind,
                    "duration_ms": max(
                        0.0, (time.monotonic() - started_at) * 1000.0
                    ),
                    "fallback_count": observation["fallback_count"],
                    "error_type": type(error).__name__,
                    **_safe_route_metadata(
                        self, model_override, observation["backend"]
                    ),
                }
                _record_observation(
                    "inference.finished", finished_payload, outcome="failed"
                )
                raise
            else:
                finished_payload = {
                    "call_id": call_id,
                    "kind": kind,
                    "duration_ms": max(
                        0.0, (time.monotonic() - started_at) * 1000.0
                    ),
                    "fallback_count": observation["fallback_count"],
                    **_safe_route_metadata(
                        self, model_override, observation["backend"]
                    ),
                }
                _record_observation(
                    "inference.finished", finished_payload, outcome="succeeded"
                )
                return result
            finally:
                _ACTIVE_INFERENCE_OBSERVATION.reset(token)

        return observed

    return decorate


class LLMRoutingError(RuntimeError):
    """Cấu hình routing không cho phép chọn một backend an toàn."""


class LocalModelUnavailableError(LLMRoutingError):
    """Một yêu cầu bắt buộc local nhưng model local chưa sẵn sàng."""


class LLMConfigurationError(LLMRoutingError):
    """Provider hoặc credential LLM không hợp lệ."""


class CloudInferenceError(RuntimeError):
    """Base class for failures produced by a configured cloud inference path."""


class CloudTransportError(CloudInferenceError):
    """The provider request failed before a usable response was available."""


class CloudOutputError(CloudInferenceError):
    """The provider returned a response that violated the text contract."""


class CloudJSONError(CloudOutputError):
    """The provider response was not a valid JSON object."""


def _is_retryable_llm_error(error: BaseException) -> bool:
    # A local generation is attempted once. Public methods own the only allowed
    # cross-backend fallback, so tenacity must not repeat it implicitly.
    return not isinstance(error, (LLMRoutingError, LocalInferenceError))

try:
    import PIL.Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

class LLM:
    def __init__(self, ego=None):
        from core.settings_manager import settings_manager
        self.settings = settings_manager
        
        # Build the Gemini client inside the retried cloud call so constructor
        # failures also leave this component as typed transport errors.
        self.client = None
        
        self.local_llm = LocalLLM()
        self.ego = ego # Tham chiếu tới SelfModel để check Fatigue

    def _provider(self) -> str:
        provider = str(self.settings.get("provider", "local")).strip().lower()
        if provider not in {"local", "gemini", "openai", "anthropic"}:
            raise LLMConfigurationError(f"Provider LLM không hợp lệ: {provider!r}")
        return provider

    @staticmethod
    def _local_is_ready() -> bool:
        from core import local_llm
        return local_llm._model_status == "ready"

    def _request_requires_local(
        self, prompt: str, *, force_local: bool = False
    ) -> bool:
        return bool(
            force_local
            or Config.USE_LOCAL_ONLY
            or self._prompt_forces_local(prompt)
        )

    def _openai_base_url(self) -> str:
        # Deployment config only: the key is sent to this host, so it must
        # never come from the dashboard-writable settings.json.
        base = getattr(Config, "OPENAI_BASE_URL", "") or "https://api.openai.com/v1"
        return str(base).strip().rstrip("/")

    def _openai_is_local(self) -> bool:
        from urllib.parse import urlparse

        host = (urlparse(self._openai_base_url()).hostname or "").lower()
        return host in {"localhost", "127.0.0.1", "::1"}

    def _openai_api_key(self) -> str:
        key = self.settings.get("openai_api_key", "")
        # Ollama / LM Studio ignore the key but the header must be present.
        return key or ("local" if self._openai_is_local() else "")

    def _openai_post(self, headers: dict, payload: dict):
        import requests

        url = f"{self._openai_base_url()}/chat/completions"
        if self._openai_is_local():
            # Never route a localhost model server through a corporate proxy.
            with requests.Session() as session:
                session.trust_env = False
                response = session.post(url, headers=headers, json=payload, timeout=300)
        else:
            response = requests.post(url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        return response

    def _cloud_backend_is_configured(self) -> bool:
        """Return whether the selected cloud backend can be called safely."""
        provider = self._provider()
        if provider in {"local", "gemini"}:
            return bool(
                self.client
                or self.settings.get("gemini_api_key", Config.API_KEY)
            )
        if provider == "openai":
            return bool(self._openai_api_key())
        if provider == "anthropic":
            return bool(self.settings.get("anthropic_api_key", ""))
        return False

    def _can_fallback_local_to_cloud(
        self, prompt: str, *, force_local: bool = False
    ) -> bool:
        return bool(
            Config.USE_HYBRID
            and not self._request_requires_local(prompt, force_local=force_local)
            and self._cloud_backend_is_configured()
        )

    def _call_local_text(self, *args, **kwargs) -> tuple[str, float]:
        try:
            result = self.local_llm.generate_text(*args, **kwargs)
        except LocalInferenceError:
            raise
        except Exception as error:
            raise LocalInferenceRuntimeError(
                "Local text inference failed."
            ) from error

        if not isinstance(result, tuple) or len(result) != 2:
            raise LocalInferenceOutputError(
                "Local text inference returned an invalid result shape."
            )
        text, entropy = result
        if not isinstance(text, str) or not text.strip():
            raise LocalInferenceOutputError(
                "Local text inference returned an empty response."
            )
        return text, entropy

    def _call_local_json(self, *args, **kwargs) -> tuple[dict, float]:
        try:
            result = self.local_llm.generate_json(*args, **kwargs)
        except LocalInferenceError:
            raise
        except Exception as error:
            raise LocalInferenceRuntimeError(
                "Local JSON inference failed."
            ) from error

        if not isinstance(result, tuple) or len(result) != 2:
            raise LocalInferenceJSONError(
                "Local JSON inference returned an invalid result shape."
            )
        data, entropy = result
        if not isinstance(data, dict):
            raise LocalInferenceJSONError(
                "Local JSON inference returned a non-object value."
            )
        return data, entropy

    def _iter_local_text(self, *args, **kwargs):
        yielded = False
        try:
            for result in self.local_llm.generate_text_stream(*args, **kwargs):
                if not isinstance(result, tuple) or len(result) != 2:
                    raise LocalInferenceOutputError(
                        "Local stream returned an invalid chunk shape."
                    )
                chunk, entropy = result
                if not isinstance(chunk, str) or not chunk.strip():
                    continue
                yielded = True
                yield chunk, entropy
        except LocalInferenceError:
            raise
        except Exception as error:
            raise LocalInferenceRuntimeError(
                "Local streaming inference failed."
            ) from error
        if not yielded:
            raise LocalInferenceOutputError(
                "Local streaming inference returned no text."
            )

    @staticmethod
    def _cloud_transport(provider: str, operation):
        """Run one provider transport operation and preserve typed failures."""
        try:
            return operation()
        except (LLMRoutingError, CloudInferenceError):
            raise
        except Exception as error:
            raise CloudTransportError(
                f"{provider} cloud transport failed."
            ) from error

    @staticmethod
    def _require_cloud_text(value: object, provider: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise CloudOutputError(
                f"{provider} returned an empty or non-text response."
            )
        return value.strip()

    @classmethod
    def _parse_cloud_json_object(cls, value: object, provider: str) -> dict:
        if not isinstance(value, str) or not value.strip():
            raise CloudJSONError(
                f"{provider} returned an empty or non-text JSON response."
            )

        text = value.strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError as direct_error:
            candidate = None
            fenced = re.search(
                r"```json\s*(.*?)\s*```",
                text,
                re.DOTALL | re.IGNORECASE,
            )
            if fenced:
                candidate = fenced.group(1)
            else:
                start = text.find("{")
                end = text.rfind("}")
                if start != -1 and end > start:
                    candidate = text[start:end + 1]
            if candidate is None:
                raise CloudJSONError(
                    f"{provider} returned malformed JSON."
                ) from direct_error
            try:
                data = json.loads(candidate)
            except json.JSONDecodeError as extracted_error:
                raise CloudJSONError(
                    f"{provider} returned malformed JSON."
                ) from extracted_error

        if not isinstance(data, dict):
            raise CloudJSONError(
                f"{provider} JSON response must be an object."
            )
        return data

    @staticmethod
    def _prompt_forces_local(prompt: str) -> bool:
        normalized = (prompt or "").strip().lower()
        for command in (
            str(value).strip().lower()
            for value in getattr(Config, "FORCE_LOCAL_COMMANDS", [])
            if str(value).strip()
        ):
            if normalized == command:
                return True
            if normalized.startswith(command) and normalized[len(command):len(command) + 1].isspace():
                return True
        return False

    def _use_local_for_request(
        self,
        prompt: str,
        model_override: str | None = None,
        *,
        force_local: bool = False,
    ) -> bool:
        """Quyết định backend một lần, đồng thời thực thi các ràng buộc cứng."""
        provider = self._provider()
        local_required = self._request_requires_local(
            prompt, force_local=force_local
        )

        if local_required:
            if not self._local_is_ready():
                raise LocalModelUnavailableError(
                    "Yêu cầu bắt buộc dùng local nhưng model local chưa sẵn sàng."
                )
            return True

        if provider == "local" and not self._local_is_ready() and not Config.USE_HYBRID:
            raise LocalModelUnavailableError(
                "Provider là local, model chưa sẵn sàng và hybrid fallback đang tắt."
            )

        # model_override là một yêu cầu cloud rõ ràng, trừ chế độ local-only ở trên.
        if model_override:
            return False
        return self._should_use_local(prompt)

    def _should_use_local(self, prompt: str = "") -> bool:
        """Quyết định dùng Local LLM dựa trên: Config, Fatigue, lệnh đặc thù hoặc settings.
        
        §5.3 FIX: Luôn kiểm tra _model_status == "ready" trước khi chọn local.
        Nếu local chưa sẵn sàng (đang load hoặc lỗi), bắt buộc fallback về Cloud
        để tránh trả về chuỗi rỗng mà không có cảnh báo (Silent Failure).
        """
        from core.local_llm import _model_status
        provider = self._provider()

        # Nếu local model đang load hoặc bị lỗi → không dùng local dù bất cứ lý do gì
        if _model_status != "ready":
            if provider == "local":
                # Log một lần khi chưa sẵn sàng để tránh spam
                if _model_status == "loading":
                    logger.debug("[HYBRID LLM]: Local model đang nạp (status='loading'). Fallback về Cloud tạm thời.")
                elif _model_status in ("error", "unavailable", "disabled"):
                    logger.warning(f"[HYBRID LLM]: Local model không khả dụng (status='{_model_status}'). Dùng Cloud.")
                return False
            return False  # provider != "local" mà local chưa ready → không route sang local

        if Config.USE_LOCAL_ONLY:
            return True

        # Local đã sẵn sàng (status == "ready") — tiếp tục logic bình thường
        if provider == "local":
            return True

        if not Config.USE_HYBRID:
            return False

        # Kiểm tra lệnh đặc thù ép dùng local
        if self._prompt_forces_local(prompt):
            return True

        if self.ego and getattr(self.ego, 'fatigue', 0.0) > 0.7:
            return True
        return False

    def _apply_cognitive_throttling(self, prompt: str, temperature: float = 0.7, max_output_tokens: Optional[int] = None, enabled: bool = True) -> tuple:
        """[Phase 24] Điều tiết động các tham số (Temp, Top_P, Tokens) dựa trên sinh lý.

        enabled=False dành cho các lệnh gọi phân tích/trích xuất có cấu trúc
        (JSON, YES/NO, sinh code): sinh lý chỉ được làm biến dạng giọng nói
        của Aura, không được làm hỏng dữ liệu mà hệ thống tự ghi vào bộ nhớ.
        """
        params = {
            "temperature": temperature,
            "top_p": 1.0,
            "max_output_tokens": max_output_tokens
        }
        
        if not self.ego or not enabled:
            return prompt, params
            
        fatigue = getattr(self.ego, 'fatigue', 0.0)
        stress = getattr(self.ego, 'stress', 0.0)
        
        # 1. Điều chỉnh Temperature: Stress gây loạn (tăng), Fatigue gây rập khuôn (giảm)
        # Stress-induced Panic: Temperature cao gây ảo giác/loạn ngôn
        if stress > 0.4:
            params["temperature"] = min(1.2, params["temperature"] + stress * 0.5)
        # Fatigue-induced Stereotype: Temperature thấp gây suy nghĩ lối mòn
        if fatigue > 0.5:
            params["temperature"] = max(0.2, params["temperature"] - fatigue * 0.4)
            
        # 2. Điều chỉnh Top_P: Fatigue làm hẹp không gian lựa chọn từ ngữ (cạn ý tưởng)
        if fatigue > 0.6:
            params["top_p"] = max(0.4, 1.0 - (fatigue - 0.6) * 1.5)

        # 3. Throttling Tokens: Stress tột độ hoặc kiệt sức bóp nghẹt độ dài câu
        if fatigue > 0.85 or stress > 0.85:
            params["max_output_tokens"] = min(params["max_output_tokens"] or 2048, 150)
            prompt += "\n[CẢNH BÁO SINH LÝ]: Bạn đang kiệt sức/stress tột độ. TRẢ LỜI CỰC NGẮN GỌN (dưới 3 câu) và không thực hiện hành động phức tạp."
        elif fatigue > 0.6 or stress > 0.6:
            params["max_output_tokens"] = min(params["max_output_tokens"] or 2048, 400)
            prompt += "\n[CẢNH BÁO SINH LÝ]: Bạn đang mệt. Hãy trả lời súc tích."
            
        return prompt, params

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(3),
        retry=retry_if_exception(_is_retryable_llm_error),
        reraise=True
    )
    def _generate_json_with_retry(self, prompt: str, temperature: float, top_p: float = 1.0, model_override: str | None = None, max_output_tokens: int | None = None, force_local: bool = False, image_path: str | None = None, backend: str | None = None) -> tuple:
        provider = self._provider()
        if backend not in {None, "local", "cloud"}:
            raise LLMConfigurationError(f"Backend LLM không hợp lệ: {backend!r}")
        use_local = (
            self._use_local_for_request(
                prompt, model_override, force_local=force_local
            )
            if backend is None
            else backend == "local"
        )

        if use_local:
            if image_path:
                logger.warning(
                    "[HYBRID LLM] Local LLM không hỗ trợ Vision; bỏ qua hình ảnh."
                )
            logger.info(
                "[HYBRID LLM] Sử dụng Local LLM (%s).",
                "force-local" if force_local else "routing",
            )
            return self._call_local_json(prompt, temperature, top_p=top_p)

        if provider == "openai":
            import requests
            api_key = self._openai_api_key()
            if not api_key:
                raise LLMConfigurationError("Thiếu OPENAI API key.")
            model = model_override or self.settings.get("openai_model") or Config.OPENAI_MODEL
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            payload = {
                "model": model,
                "messages": [{"role": "system", "content": "Follow the user message exactly. Output ONLY one valid JSON object, without markdown or comments."}, {"role": "user", "content": prompt}],
                "temperature": temperature,
                "top_p": top_p,
                "response_format": { "type": "json_object" }
            }
            if max_output_tokens: payload["max_tokens"] = max_output_tokens
            def request_openai_json():
                return self._openai_post(headers, payload)

            response = self._cloud_transport("OpenAI", request_openai_json)
            try:
                text = response.json()["choices"][0]["message"]["content"]
            except Exception as error:
                raise CloudJSONError(
                    "OpenAI returned a malformed JSON response envelope."
                ) from error
            return self._parse_cloud_json_object(text, "OpenAI"), 0.0

        elif provider == "anthropic":
            import requests
            api_key = self.settings.get("anthropic_api_key", "")
            if not api_key:
                raise LLMConfigurationError("Thiếu Anthropic API key.")
            model = model_override or self.settings.get("anthropic_model", "claude-3-haiku-20240307")
            headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": prompt + "\n\nImportant: Output ONLY valid JSON."}],
                "temperature": temperature,
                "max_tokens": max_output_tokens or 2048,
            }
            def request_anthropic_json():
                response = requests.post(
                    "https://api.anthropic.com/v1/messages",
                    headers=headers,
                    json=payload,
                    timeout=60,
                )
                response.raise_for_status()
                return response

            response = self._cloud_transport("Anthropic", request_anthropic_json)
            try:
                text = response.json()["content"][0]["text"]
            except Exception as error:
                raise CloudJSONError(
                    "Anthropic returned a malformed JSON response envelope."
                ) from error
            return self._parse_cloud_json_object(text, "Anthropic"), 0.0

        # Default to Gemini
        gemini_model = str(model_override or self.settings.get("gemini_model") or Config.MODEL_NAME)
        config_params = {"response_mime_type": "application/json", "temperature": temperature, "top_p": top_p}
        if max_output_tokens:
            config_params["max_output_tokens"] = max_output_tokens
            
        contents: list[Any] = [prompt]
        if image_path:
            if not HAS_PIL:
                logger.warning("Không thể nạp hình ảnh vì chưa cài đặt module Pillow.")
                logger.warning(
                    "Cần cài đặt Pillow để nhận dạng ảnh: pip install Pillow."
                )
            else:
                try:
                    img = PIL.Image.open(image_path)
                    contents.append(img)
                except Exception as e:
                    logger.error("Lỗi nạp hình ảnh LLM (%s)", type(e).__name__)

        if not self.client:
           api_key = self.settings.get("gemini_api_key", Config.API_KEY)
           if not api_key:
               raise LLMConfigurationError("Thiếu Gemini API key.")
           self.client = self._cloud_transport(
               "Gemini", lambda: genai.Client(api_key=api_key)
           )
           
        resp = self._cloud_transport(
            "Gemini",
            lambda: self.client.models.generate_content(
                model=gemini_model,
                contents=contents,
                config=types.GenerateContentConfig(**config_params),
            ),
        )
        
        try:
            text = resp.text
        except Exception as error:
            raise CloudJSONError(
                "Gemini returned a malformed JSON response envelope."
            ) from error
        return self._parse_cloud_json_object(text, "Gemini"), 0.0

    @_observe_inference("json", model_index=2, force_local_index=4)
    def generate_json(self, prompt: str, temperature: float = 0.1, model_override: str | None = None, max_output_tokens: int | None = None, force_local: bool = False, image_path: str | None = None, aura_state: dict | None = None, bio_throttle: bool = True) -> tuple:
        routing_prompt = prompt
        prompt, p = self._apply_cognitive_throttling(prompt, temperature, max_output_tokens, enabled=bio_throttle)
        use_local = self._use_local_for_request(
            routing_prompt, model_override, force_local=force_local
        )
        _set_inference_backend("local" if use_local else "cloud")
        try:
            return self._generate_json_with_retry(
                prompt,
                p["temperature"],
                p["top_p"],
                model_override,
                p["max_output_tokens"],
                force_local=force_local,
                image_path=image_path,
                backend="local" if use_local else "cloud",
            )
        except LocalInferenceError as e:
            # Exception messages from model/runtime libraries can echo prompts.
            # Operational logs therefore retain only the stable error class.
            logger.error("Lỗi local LLM JSON (%s)", type(e).__name__)
            if use_local and self._can_fallback_local_to_cloud(
                routing_prompt, force_local=force_local
            ):
                logger.warning(
                    "Local JSON thất bại; fallback một lần sang cloud đã cấu hình."
                )
                _set_inference_backend("cloud", fallback=True)
                return self._generate_json_with_retry(
                    prompt,
                    p["temperature"],
                    p["top_p"],
                    model_override,
                    p["max_output_tokens"],
                    force_local=False,
                    image_path=image_path,
                    backend="cloud",
                )
            raise
        except Exception as e:
            logger.error(
                "Lỗi LLM JSON sau các lần retry (%s)", type(e).__name__
            )
            if not use_local and Config.USE_HYBRID and self._local_is_ready():
                logger.warning("Cloud JSON thất bại; fallback sang local đã sẵn sàng.")
                _set_inference_backend("local", fallback=True)
                return self._call_local_json(prompt, temperature)
            raise

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(3),
        retry=retry_if_exception(_is_retryable_llm_error),
        reraise=True
    )
    def _generate_text_with_retry(self, prompt: str, temperature: float, top_p: float = 1.0, model_override: str | None = None, max_output_tokens: int | None = None, image_path: str | None = None, backend: str | None = None) -> tuple:
        provider = self._provider()
        if backend not in {None, "local", "cloud"}:
            raise LLMConfigurationError(f"Backend LLM không hợp lệ: {backend!r}")
        use_local = (
            self._use_local_for_request(prompt, model_override)
            if backend is None
            else backend == "local"
        )
        if use_local:
            if image_path:
                logger.warning(
                    "[HYBRID LLM] Local LLM không hỗ trợ Vision; bỏ qua hình ảnh."
                )
            logger.info("[HYBRID LLM] Sử dụng Local LLM theo routing.")
            return self._call_local_text(prompt, temperature, top_p=top_p)

        if provider == "openai":
            import requests
            api_key = self._openai_api_key()
            if not api_key:
                raise LLMConfigurationError("Thiếu OpenAI API key.")
            model = model_override or self.settings.get("openai_model") or Config.OPENAI_MODEL
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            payload = {
                "model": model,
                "messages": [{"role": "system", "content": "Follow the user message exactly."}, {"role": "user", "content": prompt}],
                "temperature": temperature,
                "top_p": top_p,
            }
            if max_output_tokens: payload["max_tokens"] = max_output_tokens
            def request_openai_text():
                return self._openai_post(headers, payload)

            response = self._cloud_transport("OpenAI", request_openai_text)
            try:
                text = response.json()["choices"][0]["message"]["content"]
            except Exception as error:
                raise CloudOutputError(
                    "OpenAI returned a malformed text response envelope."
                ) from error
            return self._require_cloud_text(text, "OpenAI"), 0.0

        elif provider == "anthropic":
            import requests
            api_key = self.settings.get("anthropic_api_key", "")
            if not api_key:
                raise LLMConfigurationError("Thiếu Anthropic API key.")
            model = model_override or self.settings.get("anthropic_model", "claude-3-haiku-20240307")
            headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
                "max_tokens": max_output_tokens or 2048,
            }
            def request_anthropic_text():
                response = requests.post(
                    "https://api.anthropic.com/v1/messages",
                    headers=headers,
                    json=payload,
                    timeout=60,
                )
                response.raise_for_status()
                return response

            response = self._cloud_transport("Anthropic", request_anthropic_text)
            try:
                text = response.json()["content"][0]["text"]
            except Exception as error:
                raise CloudOutputError(
                    "Anthropic returned a malformed text response envelope."
                ) from error
            return self._require_cloud_text(text, "Anthropic"), 0.0

        # Default back to Gemini
        gemini_model = str(model_override or self.settings.get("gemini_model") or Config.MODEL_NAME)
        config_params = {"temperature": temperature, "top_p": top_p}
        if max_output_tokens:
            config_params["max_output_tokens"] = max_output_tokens
            
        contents: list[Any] = [prompt]
        if image_path:
            if not HAS_PIL:
                logger.warning("Không thể nạp hình ảnh vì chưa cài đặt module Pillow.")
                logger.warning(
                    "Cần cài đặt Pillow để nhận dạng ảnh: pip install Pillow."
                )
            else:
                try:
                    img = PIL.Image.open(image_path)
                    contents.append(img)
                except Exception as e:
                    logger.error("Lỗi nạp hình ảnh LLM (%s)", type(e).__name__)

        if not self.client:
           api_key = self.settings.get("gemini_api_key", Config.API_KEY)
           if not api_key:
               raise LLMConfigurationError("Thiếu Gemini API key.")
           self.client = self._cloud_transport(
               "Gemini", lambda: genai.Client(api_key=api_key)
           )

        resp = self._cloud_transport(
            "Gemini",
            lambda: self.client.models.generate_content(
                model=gemini_model,
                contents=contents,
                config=types.GenerateContentConfig(**config_params),
            ),
        )
        try:
            text = resp.text
        except Exception as error:
            raise CloudOutputError(
                "Gemini returned a malformed text response envelope."
            ) from error
        return self._require_cloud_text(text, "Gemini"), 0.0

    @_observe_inference("text", model_index=2, force_local_index=6)
    def generate_text(self, prompt: str, temperature: float = 0.7, model_override: str | None = None, max_output_tokens: int | None = None, image_path: str | None = None, aura_state: dict | None = None, force_local: bool = False, bio_throttle: bool = True) -> tuple:
        routing_prompt = prompt
        prompt, p = self._apply_cognitive_throttling(prompt, temperature, max_output_tokens, enabled=bio_throttle)
        use_local = self._use_local_for_request(
            routing_prompt, model_override, force_local=force_local
        )
        _set_inference_backend("local" if use_local else "cloud")
        try:
            return self._generate_text_with_retry(
                prompt,
                p["temperature"],
                p["top_p"],
                model_override,
                p["max_output_tokens"],
                image_path=image_path,
                backend="local" if use_local else "cloud",
            )
        except LocalInferenceError as e:
            logger.error("Lỗi local LLM Text (%s)", type(e).__name__)
            if use_local and self._can_fallback_local_to_cloud(
                routing_prompt, force_local=force_local
            ):
                logger.warning(
                    "Local text thất bại; fallback một lần sang cloud đã cấu hình."
                )
                _set_inference_backend("cloud", fallback=True)
                return self._generate_text_with_retry(
                    prompt,
                    p["temperature"],
                    p["top_p"],
                    model_override,
                    p["max_output_tokens"],
                    image_path=image_path,
                    backend="cloud",
                )
            raise
        except Exception as e:
            logger.error(
                "Lỗi LLM Text sau các lần retry (%s)", type(e).__name__
            )
            if not use_local and Config.USE_HYBRID and self._local_is_ready():
                logger.warning("Cloud text thất bại; fallback sang local đã sẵn sàng.")
                _set_inference_backend("local", fallback=True)
                return self._call_local_text(prompt, temperature)
            raise

    def generate_text_stream(self, prompt: str, temperature: float = 0.7, tools: list | None = None, model_override: str | None = None, max_output_tokens: int | None = None, aura_state: dict | None = None, force_local: bool = False):
        routing_prompt = prompt
        prompt, p = self._apply_cognitive_throttling(prompt, temperature, max_output_tokens)
        use_local = self._use_local_for_request(
            routing_prompt, model_override, force_local=force_local
        )
        fell_back_from_local = False
        if use_local:
            local_yielded = False
            try:
                for chunk, _ in self._iter_local_text(
                    prompt, p["temperature"], top_p=p["top_p"]
                ):
                    local_yielded = True
                    yield chunk
                return
            except LocalInferenceError as e:
                logger.error("Lỗi local LLM Stream (%s)", type(e).__name__)
                if (
                    not local_yielded
                    and self._can_fallback_local_to_cloud(
                        routing_prompt, force_local=force_local
                    )
                ):
                    logger.warning(
                        "Local stream thất bại trước chunk đầu; fallback một lần sang cloud."
                    )
                    fell_back_from_local = True
                else:
                    raise

        cloud_yielded = False
        try:
            provider = self._provider()
            if provider in {"openai", "anthropic"}:
                # Hai provider này chưa có transport streaming riêng. Giữ đúng
                # provider bằng cách yield kết quả hoàn chỉnh thay vì lén đổi sang Gemini.
                text, _ = self._generate_text_with_retry(
                    prompt,
                    p["temperature"],
                    p["top_p"],
                    model_override,
                    p["max_output_tokens"],
                    backend="cloud",
                )
                # Non-streaming cloud paths enforce this before returning.
                text = self._require_cloud_text(text, provider.title())
                cloud_yielded = True
                yield text
                return

            if not self.client:
                api_key = self.settings.get("gemini_api_key", Config.API_KEY)
                if not api_key:
                    raise LLMConfigurationError("Thiếu Gemini API key.")
                self.client = self._cloud_transport(
                    "Gemini", lambda: genai.Client(api_key=api_key)
                )
            config_params: dict[str, Any] = {"temperature": p["temperature"], "top_p": p["top_p"]}
            if p["max_output_tokens"]:
                config_params["max_output_tokens"] = p["max_output_tokens"]
            if tools:
                config_params["tools"] = tools
                
            responses = self._cloud_transport(
                "Gemini",
                lambda: self.client.models.generate_content_stream(
                    model=model_override or self.settings.get("gemini_model") or Config.MODEL_NAME,
                    contents=prompt,
                    config=types.GenerateContentConfig(**config_params),
                ),
            )
            for chunk in responses:
                try:
                    text = chunk.text
                except Exception as error:
                    raise CloudOutputError(
                        "Gemini stream returned a malformed chunk."
                    ) from error
                if text is None or text == "":
                    continue
                if not isinstance(text, str):
                    raise CloudOutputError(
                        "Gemini stream returned a non-text chunk."
                    )
                if not text.strip():
                    continue
                cloud_yielded = True
                yield text
            if not cloud_yielded:
                raise CloudOutputError(
                    "Gemini streaming inference returned no text chunks."
                )
        except Exception as e:
            typed_error = (
                e
                if isinstance(e, (LLMRoutingError, CloudInferenceError))
                else CloudTransportError("Cloud streaming transport failed.")
            )
            logger.error("Lỗi LLM Stream (%s)", type(e).__name__)
            if (
                not fell_back_from_local
                and not cloud_yielded
                and Config.USE_HYBRID
                and self._local_is_ready()
            ):
                for chunk, _ in self._iter_local_text(prompt, temperature):
                    yield chunk
                return
            if typed_error is e:
                raise
            raise typed_error from e
