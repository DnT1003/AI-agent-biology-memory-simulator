import logging
import math
from typing import Any, Literal

from colorama import Fore, Style

from config import Config, _optional_service_auth_token


logger = logging.getLogger(__name__)
PerceptionMode = Literal["remote", "native"]

NEUTRAL_RESULT = {"valence": 0.0, "arousal": 0.5, "importance": 0.5}


class PerceptionError(RuntimeError):
    """Base error for local-perception failures."""


class PerceptionNotReadyError(PerceptionError):
    """Raised when the native sentiment model is unavailable."""


class LocalPerception:
    """Sentiment inference with separate remote and native execution modes.

    The main brain uses the backwards-compatible ``remote`` default. The GPU
    service must opt into ``native`` so a failed model load can never make the
    service call its own ``/analyze`` endpoint.
    """

    def __init__(
        self,
        model_name: str | None = None,
        *,
        mode: PerceptionMode = "remote",
        service_url: str | None = None,
        service_auth_token: str | None = None,
        http_client: Any | None = None,
    ):
        if mode not in ("remote", "native"):
            raise ValueError("mode must be either 'remote' or 'native'")

        self.mode: PerceptionMode = mode
        self.model_name = model_name or Config.LOCAL_PERCEPTION_MODEL
        self.service_url = (service_url or Config.GPU_SERVICE_URL).rstrip("/")
        raw_token = (
            service_auth_token
            if service_auth_token is not None
            else Config.GPU_SERVICE_AUTH_TOKEN
        )
        self.service_auth_token: str | None = _optional_service_auth_token(raw_token)
        self._http_client = http_client
        self.sentiment_analyzer = None
        self.device: str | None = None
        self.init_error: str | None = None

        # Remote clients must not import torch/transformers or load a model.
        if self.mode == "native":
            self._initialize_native_backend()

    @property
    def is_ready(self) -> bool:
        return self.mode == "native" and self.sentiment_analyzer is not None

    def _initialize_native_backend(self) -> None:
        print(
            f"{Fore.LIGHTCYAN_EX}👁️ [LOCAL PERCEPTION]: "
            f"Đang khởi tạo mô hình {self.model_name}...{Style.RESET_ALL}"
        )
        try:
            import torch  # type: ignore
            from transformers import pipeline  # type: ignore

            self.device = "cuda" if torch.cuda.is_available() else "cpu"
            self.sentiment_analyzer = pipeline(
                "text-classification",
                model=self.model_name,
                device=0 if self.device == "cuda" else -1,
            )
            print(
                f"{Fore.GREEN}✅ [LOCAL PERCEPTION]: "
                f"Engine sẵn sàng trên {self.device.upper()}.{Style.RESET_ALL}"
            )
        except Exception as exc:
            self.init_error = str(exc)
            self.sentiment_analyzer = None
            logger.error("[LocalPerception Native Init Error]: %s", exc, exc_info=True)

    def analyze(self, text: str) -> dict:
        if self.mode == "remote":
            return self._analyze_remote(text)
        return self._analyze_native(text)

    def _analyze_remote(self, text: str) -> dict:
        if not self.service_auth_token:
            logger.warning(
                "[LocalPerception Remote Error]: Missing or invalid GPU service auth token"
            )
            return dict(NEUTRAL_RESULT)

        client = self._http_client
        if client is None:
            import requests

            client = requests

        try:
            response = client.post(
                f"{self.service_url}/analyze",
                json={"text": text},
                headers={"X-Aura-Internal-Token": self.service_auth_token},
                timeout=10,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("GPU service returned an invalid sentiment payload")
            ranges = {
                "valence": (-1.0, 1.0),
                "arousal": (0.0, 1.0),
                "importance": (0.0, 1.0),
            }
            for field, (minimum, maximum) in ranges.items():
                value = payload.get(field)
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(float(value))
                    or not minimum <= float(value) <= maximum
                ):
                    raise ValueError(f"GPU service returned invalid {field}")
            return payload
        except Exception as exc:
            # Preserve the historical neutral fallback for brain callers while
            # logging the outage. Native mode never takes this branch.
            logger.warning("[LocalPerception Remote Error]: %s", exc)
            return dict(NEUTRAL_RESULT)

    def _analyze_native(self, text: str) -> dict:
        if not self.is_ready:
            raise PerceptionNotReadyError(
                self.init_error or "Native sentiment model is not ready"
            )

        try:
            results = self.sentiment_analyzer(text)
            if not results:
                raise PerceptionError("Native sentiment model returned no result")

            result = results[0]
            label = str(result["label"])
            score = float(result["score"])
            if not math.isfinite(score) or not 0.0 <= score <= 1.0:
                raise PerceptionError("Native sentiment model returned an invalid score")

            # CardiffNLP publishes semantic labels (negative/neutral/positive),
            # Vietnamese ViSoBERT/PhoBERT models publish NEG/NEU/POS. Generic
            # LABEL_0..2 follows the CardiffNLP order (neg, neu, pos); ViSoBERT
            # orders ids differently (0=NEG, 1=POS, 2=NEU), so only its named
            # labels are trusted here.
            normalized_label = label.strip().lower()

            if normalized_label in {"negative", "neg", "label_0"}:
                valence = -0.7 * score
                arousal = 0.8
            elif normalized_label in {"neutral", "neu", "label_1"}:
                valence = 0.0
                arousal = 0.3
            elif normalized_label in {"positive", "pos", "label_2"}:
                valence = 0.7 * score
                arousal = 0.5
            else:
                raise PerceptionError(
                    f"Native sentiment model returned an unknown label: {label!r}"
                )

            importance = min(
                0.9, 0.3 + (score * 0.4) + (min(len(text), 100) / 200)
            )
            return {
                "valence": valence,
                "arousal": arousal,
                "importance": importance,
                "raw_label": label,
                "confidence": score,
            }
        except PerceptionError:
            raise
        except Exception as exc:
            raise PerceptionError("Native sentiment analysis failed") from exc


if __name__ == "__main__":
    perception = LocalPerception(mode="native")
    samples = [
        "I love you so much!",
        "You are so annoying and stupid.",
        "What is the weather today?",
        "Hôm nay trời đẹp quá, đi chơi không?",
    ]
    for sample in samples:
        try:
            result = perception.analyze(sample)
        except PerceptionError as exc:
            result = {"error": str(exc)}
        print(f"Text: {sample}\nResult: {result}\n")
