# LLM Component wrapper cho Google GenAI
import json
import logging
from google import genai
from google.genai import types
from config import Config
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type

logger = logging.getLogger(__name__)

class LLM:
    def __init__(self):
        self.client = genai.Client(api_key=Config.API_KEY)

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type(Exception),
        reraise=True
    )
    def _generate_json_with_retry(self, prompt: str, temperature: float, model_override: str) -> dict:
        resp = self.client.models.generate_content(
            model=model_override or Config.MODEL_NAME, 
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json", temperature=temperature)
        )
        data = json.loads(resp.text)
        if isinstance(data, list):
            return data[0] if len(data) > 0 else {}
        return data

    def generate_json(self, prompt: str, temperature: float = 0.1, model_override: str = None) -> dict:
        try:
            return self._generate_json_with_retry(prompt, temperature, model_override)
        except Exception as e:
            logger.error(f"Lỗi LLM JSON (đã retry 3 lần thất bại): {e}")
            return {}

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type(Exception),
        reraise=True
    )
    def _generate_text_with_retry(self, prompt: str, temperature: float, model_override: str) -> str:
        resp = self.client.models.generate_content(
            model=model_override or Config.MODEL_NAME, 
            contents=prompt,
            config=types.GenerateContentConfig(temperature=temperature)
        )
        return resp.text.strip()

    def generate_text(self, prompt: str, temperature: float = 0.7, model_override: str = None) -> str:
        try:
            return self._generate_text_with_retry(prompt, temperature, model_override)
        except Exception as e:
            logger.error(f"Lỗi LLM Text (đã retry 3 lần thất bại): {e}")
            return ""

    def generate_text_stream(self, prompt: str, temperature: float = 0.7, tools: list = None, model_override: str = None):
        # Không dùng @retry cho generator vì nó vỡ state stream nếu fail giữa chừng. Nhưng có thể wrap lệnh gọi initial.
        try:
            config_params = {"temperature": temperature}
            if tools:
                config_params["tools"] = tools
                
            responses = self.client.models.generate_content_stream(
                model=model_override or Config.MODEL_NAME, 
                contents=prompt,
                config=types.GenerateContentConfig(**config_params)
            )
            for chunk in responses:
                if chunk.text:
                    yield chunk.text
        except Exception as e:
            logger.error(f"Lỗi LLM Stream: {e}")
