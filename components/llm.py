# LLM Component wrapper cho Google GenAI
import json
import logging
from google import genai
from google.genai import types
from config import Config
from colorama import Fore, Style
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type

logger = logging.getLogger(__name__)

from core.local_llm import LocalLLM

logger = logging.getLogger(__name__)

class LLM:
    def __init__(self, ego=None):
        self.client = genai.Client(api_key=Config.API_KEY)
        self.local_llm = LocalLLM()
        self.ego = ego # Tham chiếu tới SelfModel để check Fatigue

    def _should_use_local(self) -> bool:
        """Quyết định dùng Local LLM nếu Aura quá mệt mỏi (> 0.6) hoặc mất kết nối"""
        if self.ego and getattr(self.ego, 'fatigue', 0.0) > 0.6:
            return True
        return False

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type(Exception),
        reraise=True
    )
    def _generate_json_with_retry(self, prompt: str, temperature: float, model_override: str, max_output_tokens: int = None) -> dict:
        if self._should_use_local() and not model_override:
            print(f"{Fore.LIGHTBLACK_EX}⚡ [HYBRID LLM]: Hệ thần kinh mệt mỏi. Chuyển sang Local LLM (Phi-3) để phản xạ nhanh.{Style.RESET_ALL}")
            return self.local_llm.generate_json(prompt, temperature)

        config_params = {"response_mime_type": "application/json", "temperature": temperature}
        if max_output_tokens:
            config_params["max_output_tokens"] = max_output_tokens
            
        resp = self.client.models.generate_content(
            model=model_override or Config.MODEL_NAME, 
            contents=prompt,
            config=types.GenerateContentConfig(**config_params)
        )
        data = json.loads(resp.text)
        if isinstance(data, list):
            return data[0] if len(data) > 0 else {}
        return data

    def generate_json(self, prompt: str, temperature: float = 0.1, model_override: str = None, max_output_tokens: int = None) -> dict:
        try:
            return self._generate_json_with_retry(prompt, temperature, model_override, max_output_tokens)
        except Exception as e:
            logger.error(f"Lỗi LLM JSON (đã retry 3 lần thất bại): {e}")
            # Fallback cuối cùng sang local nếu cloud chết
            return self.local_llm.generate_json(prompt, temperature)

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type(Exception),
        reraise=True
    )
    def _generate_text_with_retry(self, prompt: str, temperature: float, model_override: str, max_output_tokens: int = None) -> str:
        if self._should_use_local() and not model_override:
            print(f"{Fore.LIGHTBLACK_EX}⚡ [HYBRID LLM]: Hệ thần kinh mệt mỏi. Chuyển sang Local LLM (Phi-3) để phản xạ nhanh.{Style.RESET_ALL}")
            return self.local_llm.generate_text(prompt, temperature)

        config_params = {"temperature": temperature}
        if max_output_tokens:
            config_params["max_output_tokens"] = max_output_tokens
            
        resp = self.client.models.generate_content(
            model=model_override or Config.MODEL_NAME, 
            contents=prompt,
            config=types.GenerateContentConfig(**config_params)
        )
        return resp.text.strip()

    def generate_text(self, prompt: str, temperature: float = 0.7, model_override: str = None, max_output_tokens: int = None) -> str:
        try:
            return self._generate_text_with_retry(prompt, temperature, model_override, max_output_tokens)
        except Exception as e:
            logger.error(f"Lỗi LLM Text (đã retry 3 lần thất bại): {e}")
            return self.local_llm.generate_text(prompt, temperature)

    def generate_text_stream(self, prompt: str, temperature: float = 0.7, tools: list = None, model_override: str = None, max_output_tokens: int = None):
        if self._should_use_local() and not model_override:
            yield from self.local_llm.generate_text_stream(prompt, temperature)
            return

        try:
            config_params = {"temperature": temperature}
            if max_output_tokens:
                config_params["max_output_tokens"] = max_output_tokens
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
            yield from self.local_llm.generate_text_stream(prompt, temperature)
