"""
local_llm.py  — Gemma 4 E4B Local LLM (thay thế Ollama)

Sử dụng Unsloth + HuggingFace để chạy Gemma 4 E4B offline.
Model path được load lazy (lần đầu gọi mới nạp vào VRAM).
"""

import json
import logging
import re
import threading
import time

logger = logging.getLogger(__name__)

# ── Lazy-load state ────────────────────────────────────────────────────────────
_model = None
_tokenizer = None
_model_lock = threading.Lock()
_model_status = "not_loaded"   # not_loaded | loading | ready | error | unavailable | disabled
_load_error = ""


class LocalInferenceError(RuntimeError):
    """Base error for a local inference request that produced no usable result."""


class LocalInferenceUnavailableError(LocalInferenceError):
    """The local model cannot currently serve inference requests."""


class LocalInferenceRuntimeError(LocalInferenceError):
    """The local model failed while tokenizing or generating a response."""


class LocalInferenceOutputError(LocalInferenceError):
    """The local model completed but returned an unusable output."""


class LocalInferenceJSONError(LocalInferenceOutputError):
    """The local model did not produce a valid JSON object."""


def _load_model_once(model_path: str):
    """Nạp model vào VRAM lần đầu tiên (thread-safe, chỉ chạy 1 lần)."""
    global _model, _tokenizer, _model_status, _load_error
    with _model_lock:
        if _model_status in ("ready", "loading"):
            return
        _model_status = "loading"

    try:
        import torch #type: ignore
        import torch.utils._pytree  #type: ignore
        # Patch tương thích torchao + PyTorch >= 2.6.0
        if not hasattr(torch.utils._pytree, "register_constant"):
            torch.utils._pytree.register_constant = lambda x: x

        from unsloth import FastLanguageModel  # type: ignore

        logger.info(f"[LocalLLM] Đang nạp Gemma 4 E4B từ {model_path} ...")
        m, tok = FastLanguageModel.from_pretrained(
            model_name=model_path,
            max_seq_length=2048,
            load_in_4bit=True,
        )
        FastLanguageModel.for_inference(m)

        with _model_lock:
            _model = m
            _tokenizer = tok
            _model_status = "ready"
        logger.info("[LocalLLM] ✅ Gemma 4 E4B sẵn sàng!")

    except ImportError as e:
        # unsloth hoặc torchao không tương thích với phiên bản CUDA/torch hiện tại
        # → Graceful degradation: hệ thống tiếp tục chạy với Gemini Cloud
        _load_error = type(e).__name__
        with _model_lock:
            _model_status = "unavailable"
        logger.warning(
            f"[LocalLLM] ⚠️ Bỏ qua Gemma E4B — unsloth không tương thích với môi trường hiện tại.\n"
            f"  Loại lỗi: {type(e).__name__}\n"
            f"  → Hệ thống sẽ dùng Gemini Cloud thay thế."
        )
    except Exception as e:
        _load_error = type(e).__name__
        with _model_lock:
            _model_status = "error"
        logger.error("[LocalLLM] ❌ Lỗi load model (%s)", type(e).__name__)


class LocalLLM:
    """Wrapper cho Gemma 4 E4B chạy offline qua Unsloth (thay thế Ollama)."""

    def __init__(self):
        from config import Config
        self.model_path = Config.GEMMA_MODEL_PATH
        self.max_new_tokens = 512
        if not Config.LOCAL_LLM_ENABLED:
            global _model_status
            with _model_lock:
                if _model_status != "ready":
                    _model_status = "disabled"
            logger.info("[LocalLLM] Local backend is disabled by configuration.")
            return
        # Bắt đầu load model trong background ngay khi khởi tạo
        t = threading.Thread(
            target=_load_model_once, args=(self.model_path,), daemon=True
        )
        t.start()

    # ── Nội bộ ────────────────────────────────────────────────────────────────

    def _wait_ready(self, timeout: float = 120.0) -> bool:
        """Chờ model load xong (tối đa timeout giây). Trả về True nếu ready."""
        # Nếu unavailable (CUDA/unsloth conflict) → trả về False ngay, không chờ
        if _model_status in ("unavailable", "disabled"):
            return False
        deadline = time.time() + timeout
        while time.time() < deadline:
            if _model_status == "ready":
                return True
            if _model_status in ("error", "unavailable", "disabled"):
                return False
            time.sleep(1.0)
        return False

    def _infer(self, prompt: str, temperature: float = 0.7,
               max_new_tokens: int | None = None) -> str:
        """Generate non-empty text or raise a typed local-inference error."""
        if not self._wait_ready():
            detail = _load_error or f"status={_model_status}"
            raise LocalInferenceUnavailableError(
                f"Local model is not ready for inference ({detail})."
            )

        with _model_lock:
            if _model is None or _tokenizer is None:
                raise LocalInferenceUnavailableError(
                    "Local model reported ready without model/tokenizer state."
                )
            try:
                import torch  # type: ignore

                inputs = _tokenizer([prompt], return_tensors="pt").to("cuda")
                n_tok = max_new_tokens or self.max_new_tokens

                with torch.no_grad():
                    output_ids = _model.generate(
                        **inputs,
                        max_new_tokens=n_tok,
                        temperature=temperature,
                        do_sample=temperature > 0,
                    )

                input_len = inputs["input_ids"].shape[1]
                generated = output_ids[0][input_len:]
                text = _tokenizer.decode(
                    generated, skip_special_tokens=True
                ).strip()

            except Exception as e:
                # Explicit /local requests share this boundary. Third-party
                # exception messages/tracebacks can echo prompt fragments, so
                # persist only the stable exception class.
                logger.error(
                    "[LocalLLM] Inference failed (%s)", type(e).__name__
                )
                raise LocalInferenceRuntimeError(
                    "Local model inference failed."
                ) from e

        if not text:
            raise LocalInferenceOutputError(
                "Local model returned an empty text response."
            )
        return text

    # ── Public API (giữ nguyên signature để tương thích toàn bộ codebase) ──────

    def generate_text(
        self,
        prompt: str,
        temperature: float = 0.7,
        top_p: float = 1.0,
        top_k: int = 40,
        aura_state: dict | None = None,
        model_override: str | None = None,
    ) -> tuple[str, float]:
        """
        Sinh văn bản tự do.
        Trả về (text, entropy) — entropy luôn là 0.0 (Gemma không expose).
        """
        full_prompt = self._build_prompt(prompt, aura_state)
        text = self._infer(full_prompt, temperature=temperature)
        return text, 0.0

    def generate_json(
        self,
        prompt: str,
        temperature: float = 0.1,
        top_p: float = 1.0,
        top_k: int = 40,
        aura_state: dict | None = None,
        model_override: str | None = None,
    ) -> tuple[dict, float]:
        """
        Sinh JSON.  Trả về (dict, entropy).
        Nếu parse thất bại 3 lần, raise ``LocalInferenceJSONError``.
        """
        json_prompt = (
            f"{prompt}\n\n"
            "IMPORTANT: Return ONLY a valid JSON object. "
            "Do not include any explanation or markdown backticks outside the JSON."
        )
        full_prompt = self._build_prompt(json_prompt, aura_state)

        for attempt in range(3):
            raw = self._infer(full_prompt, temperature=temperature)
            # Làm sạch markdown fence nếu có
            raw = re.sub(r"^```json\s*", "", raw.strip())
            raw = re.sub(r"^```\s*", "", raw.strip())
            raw = re.sub(r"\s*```$", "", raw.strip())

            # Trích đoạn JSON đầu tiên nếu model sinh thêm text dư
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0)), 0.0
                except json.JSONDecodeError:
                    pass

            # Raw local-model output can repeat private input; never persist it.
            logger.warning(
                "[LocalLLM] JSON parse failed on attempt %d", attempt + 1
            )

        logger.error("[LocalLLM] Không parse được JSON sau 3 lần thử.")
        raise LocalInferenceJSONError(
            "Local model did not return a valid JSON object after 3 attempts."
        )

    def generate_text_stream(
        self,
        prompt: str,
        temperature: float = 0.7,
        top_p: float = 1.0,
        top_k: int = 40,
        aura_state: dict | None = None,
    ):
        """
        Stream sinh text — yield từng chunk (text, entropy).
        Vì Gemma chạy local, ta sinh 1 lần rồi yield từng từ.
        """
        full_prompt = self._build_prompt(prompt, aura_state)
        text = self._infer(full_prompt, temperature=temperature)
        # Giả lập stream theo từ
        for word in text.split():
            yield word + " ", 0.0
            time.sleep(0.01)

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _build_prompt(prompt: str, aura_state: dict | None = None) -> str:
        """Ghép thông tin trạng thái sinh học vào đầu prompt (nếu có)."""
        if not aura_state:
            return prompt
        bio = (
            f"[BIO] dopamine={aura_state.get('dopamine', 0.5):.2f} "
            f"stress={aura_state.get('stress', 0.1):.2f} "
            f"curiosity={aura_state.get('curiosity', 0.5):.2f}\n"
        )
        return bio + prompt

    @staticmethod
    def get_status() -> dict:
        """Trả về trạng thái hiện tại của model (cho API /status nếu cần)."""
        return {
            "model_status": _model_status,
            "model_error": _load_error,
        }
