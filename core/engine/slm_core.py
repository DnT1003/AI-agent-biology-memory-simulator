import logging
import os
import sys
from collections.abc import Mapping
from typing import Any, Literal

from config import Config, _optional_service_auth_token


logger = logging.getLogger(__name__)

SLMMode = Literal["remote", "native"]


class SLMError(RuntimeError):
    """Base error for SLM routing and inference failures."""


class SLMNotReadyError(SLMError):
    """Raised when native inference is requested before the model is ready."""


class SLMServiceError(SLMError):
    """Raised when the remote GPU service cannot provide a valid response."""


class SLMCore:
    """SLM inference wrapper with structurally separate remote and native modes.

    ``remote`` is the backwards-compatible default for the main brain process.
    ``native`` is reserved for the GPU service and never performs HTTP calls.
    """

    def __init__(
        self,
        *,
        mode: SLMMode = "remote",
        service_url: str | None = None,
        service_auth_token: str | None = None,
        http_client: Any | None = None,
    ):
        if mode not in ("remote", "native"):
            raise ValueError("mode must be either 'remote' or 'native'")

        self.mode: SLMMode = mode
        self.service_url = (service_url or Config.GPU_SERVICE_URL).rstrip("/")
        raw_token = (
            service_auth_token
            if service_auth_token is not None
            else Config.GPU_SERVICE_AUTH_TOKEN
        )
        self.service_auth_token: str | None = _optional_service_auth_token(raw_token)
        self._http_client = http_client

        self.device = "cpu"
        self.model = None
        self.tokenizer = None
        self.is_ready = False
        self.init_error: str | None = None

        self._torch = None
        self._model_class = None
        self._tokenizer_class = None
        self._block_size = 0

        self.model_path = Config.SLM_MODEL_PATH
        self.vocab_path = os.path.join(Config.SLM_MODEL_DIR, "vocab.json")

        # Remote clients must not import torch/NanoGPT or allocate model memory.
        if self.mode == "native":
            self._initialize_native_backend()

    def _initialize_native_backend(self) -> None:
        try:
            self._validate_native_assets()
            import torch  # type: ignore

            if Config.SLM_DIR not in sys.path:
                sys.path.append(Config.SLM_DIR)

            from model import AuraFlashModel, block_size  # type: ignore
            from tokenizer import BPETokenizer  # type: ignore

            self._torch = torch
            self._model_class = AuraFlashModel
            self._tokenizer_class = BPETokenizer
            self._block_size = int(block_size)
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
            self._init_tokenizer()
            self.load_model()
        except Exception as exc:
            self.init_error = str(exc)
            self.is_ready = False
            logger.error("[SLM Native Init Error]: %s", exc, exc_info=True)

    def _validate_native_assets(self) -> None:
        if not os.path.isfile(self.model_path):
            raise FileNotFoundError(f"SLM checkpoint not found: {self.model_path}")
        if not os.path.isfile(self.vocab_path):
            raise FileNotFoundError(f"SLM vocabulary not found: {self.vocab_path}")

    def _init_tokenizer(self) -> None:
        if self._tokenizer_class is None:
            return
        try:
            tokenizer = self._tokenizer_class()
            tokenizer.load(self.vocab_path)
            if not getattr(tokenizer, "vocab_size", 0):
                raise ValueError("SLM vocabulary is empty")
            self.tokenizer = tokenizer
        except Exception as exc:
            self.init_error = str(exc)
            self.tokenizer = None
            logger.error("[SLM Tokenizer Init Error]: %s", exc, exc_info=True)

    def load_model(self) -> None:
        if self.mode != "native":
            raise RuntimeError("load_model() is only valid in native mode")
        if self._model_class is None or self._torch is None:
            self.is_ready = False
            return

        try:
            self._validate_native_assets()
            if not self.tokenizer:
                self._init_tokenizer()
            if not self.tokenizer or not getattr(self.tokenizer, "vocab_size", 0):
                raise RuntimeError("SLM tokenizer is not ready")

            model_vocab_size = int(self.tokenizer.vocab_size)

            self.model = self._model_class(model_vocab_size)
            try:
                state = self._torch.load(
                    self.model_path, map_location=self.device, weights_only=True
                )
            except TypeError:
                state = self._torch.load(self.model_path, map_location=self.device)
            if not isinstance(state, Mapping):
                raise ValueError("SLM checkpoint does not contain a state mapping")

            state = {
                key.replace(".moe.", ".mlp."): value
                for key, value in state.items()
            }
            self.model.load_state_dict(state, strict=False)

            dtype = self._torch.bfloat16 if self.device == "cuda" else self._torch.float32
            self.model.to(device=self.device, dtype=dtype)
            self.model.eval()
            self.is_ready = self.model is not None and self.tokenizer is not None
            self.init_error = None if self.is_ready else "Native SLM is not ready"
        except Exception as exc:
            self.init_error = str(exc)
            self.is_ready = False
            logger.error("[SLM Model Load Error]: %s", exc, exc_info=True)

    def generate_thought(self, prompt_text: str, max_tokens: int = 50) -> str:
        """Generate a short thought using exactly the configured execution mode."""
        if self.mode == "remote":
            return self._generate_remote(prompt_text, max_tokens)
        return self._generate_native(prompt_text, max_tokens)

    def _generate_remote(self, prompt_text: str, max_tokens: int) -> str:
        if not self.service_auth_token:
            raise SLMServiceError("GPU service authentication token is missing or invalid")

        client = self._http_client
        if client is None:
            import requests

            client = requests

        try:
            response = client.post(
                f"{self.service_url}/generate",
                json={"prompt": prompt_text, "max_new_tokens": max_tokens},
                headers={"X-Aura-Internal-Token": self.service_auth_token},
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()
            thought = payload.get("thought") if isinstance(payload, dict) else None
            if not isinstance(thought, str) or not thought.strip():
                raise ValueError("GPU service returned an invalid thought payload")
            return thought
        except Exception as exc:
            raise SLMServiceError("GPU SLM service request failed") from exc

    def _generate_native(self, prompt_text: str, max_tokens: int) -> str:
        if not self.is_ready or self.model is None or self.tokenizer is None:
            raise SLMNotReadyError(self.init_error or "Native SLM is not ready")
        if self._torch is None:
            raise SLMNotReadyError("Torch is unavailable for native SLM inference")

        try:
            encoded = self.tokenizer.encode(prompt_text)
            if not encoded:
                raise ValueError("Prompt produced no tokens")

            context = self._torch.tensor(
                encoded, dtype=self._torch.long, device=self.device
            ).unsqueeze(0)
            context = context[:, -self._block_size :]

            device_type = "cuda" if self.device == "cuda" else "cpu"
            autocast_enabled = device_type == "cuda"
            with self._torch.no_grad(), self._torch.amp.autocast(
                device_type,
                dtype=self._torch.bfloat16,
                enabled=autocast_enabled,
            ):
                output = self.model.generate(context, max_new_tokens=max_tokens)

            return self.tokenizer.decode(output[0].tolist())
        except Exception as exc:
            raise SLMError("Native SLM inference failed") from exc
        finally:
            if self.device == "cuda":
                self._torch.cuda.empty_cache()

    def log_experience_for_finetuning(self, text_data: str) -> None:
        """Append data to a finetune queue for offline training."""
        try:
            log_path = os.path.join(Config.OUTPUT_DIR, "slm_finetune_data.txt")
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as file_handle:
                file_handle.write(text_data.strip() + "\n\n")
            print("[SLM]: Logged finetune experience.")
        except Exception as exc:
            logger.error("[SLM Finetune Logging Error]: %s", exc, exc_info=True)
