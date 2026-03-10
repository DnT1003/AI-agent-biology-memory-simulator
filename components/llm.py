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
import PIL.Image

logger = logging.getLogger(__name__)

class LLM:
    def __init__(self, ego=None):
        self.client = genai.Client(api_key=Config.API_KEY)
        self.local_llm = LocalLLM()
        self.ego = ego # Tham chiếu tới SelfModel để check Fatigue

    def _should_use_local(self, prompt: str = "") -> bool:
        """Quyết định dùng Local LLM dựa trên: Config, Fatigue, lệnh đặc thù hoặc mất mạng"""
        if Config.USE_LOCAL_ONLY:
            return True
            
        # Kiểm tra lệnh đặc thù ép dùng local
        if prompt and any(cmd in prompt.lower() for cmd in Config.FORCE_LOCAL_COMMANDS):
            return True
            
        if self.ego and getattr(self.ego, 'fatigue', 0.0) > 0.7:
            return True
        return False

    def _apply_cognitive_throttling(self, prompt: str, max_output_tokens: int = None) -> tuple:
        """[Phase 22] Điều tiết năng lực xử lý (Tokens) dựa trên độ mệt mỏi và stress."""
        if not self.ego:
            return prompt, max_output_tokens
            
        fatigue = getattr(self.ego, 'fatigue', 0.0)
        stress = getattr(self.ego, 'stress', 0.0)
        
        # Throttling Level 2: Kiệt sức hoặc stress cực độ
        if fatigue > 0.85 or stress > 0.85:
            max_output_tokens = min(max_output_tokens or 2048, 150)
            prompt += "\n[CẢNH BÁO SINH LÝ]: Bạn đang kiệt sức/stress tột độ. TRẢ LỜI CỰC NGẮN GỌN (dưới 3 câu) và không thực hiện hành động phức tạp."
        # Throttling Level 1: Mệt mỏi trung bình
        elif fatigue > 0.6 or stress > 0.6:
            max_output_tokens = min(max_output_tokens or 2048, 400)
            prompt += "\n[CẢNH BÁO SINH LÝ]: Bạn đang mệt. Hãy trả lời súc tích."
            
        return prompt, max_output_tokens

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type(Exception),
        reraise=True
    )
    def _generate_json_with_retry(self, prompt: str, temperature: float, model_override: str, max_output_tokens: int = None, force_local: bool = False, image_path: str = None) -> dict:
        if (self._should_use_local(prompt) or force_local) and not model_override:
            if image_path:
                print(f"{Fore.YELLOW}⚠️ [HYBRID LLM]: Local LLM (Phi-3) không hỗ trợ Vision. Bỏ qua hình ảnh.{Style.RESET_ALL}")
            print(f"{Fore.LIGHTBLACK_EX}⚡ [HYBRID LLM]: {'Force Local' if force_local else 'Hệ thần kinh mệt mỏi'}. Sử dụng Local LLM (Phi-3).{Style.RESET_ALL}")
            return self.local_llm.generate_json(prompt, temperature)

        config_params = {"response_mime_type": "application/json", "temperature": temperature}
        if max_output_tokens:
            config_params["max_output_tokens"] = max_output_tokens
            
        contents = [prompt]
        if image_path:
            try:
                img = PIL.Image.open(image_path)
                contents.append(img)
            except Exception as e:
                logger.error(f"Lỗi nạp hình ảnh LLM: {e}")

        resp = self.client.models.generate_content(
            model=model_override or Config.MODEL_NAME, 
            contents=contents,
            config=types.GenerateContentConfig(**config_params)
        )
        data = json.loads(resp.text)
        if isinstance(data, list):
            return data[0] if len(data) > 0 else {}
        return data

    def generate_json(self, prompt: str, temperature: float = 0.1, model_override: str = None, max_output_tokens: int = None, force_local: bool = False, image_path: str = None) -> dict:
        prompt, max_output_tokens = self._apply_cognitive_throttling(prompt, max_output_tokens)
        try:
            return self._generate_json_with_retry(prompt, temperature, model_override, max_output_tokens, force_local=force_local, image_path=image_path)
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
    def _generate_text_with_retry(self, prompt: str, temperature: float, model_override: str, max_output_tokens: int = None, image_path: str = None) -> str:
        if self._should_use_local(prompt) and not model_override:
            if image_path:
                print(f"{Fore.YELLOW}⚠️ [HYBRID LLM]: Local LLM (Phi-3) không hỗ trợ Vision. Bỏ qua hình ảnh.{Style.RESET_ALL}")
            print(f"{Fore.LIGHTBLACK_EX}⚡ [HYBRID LLM]: Hệ thần kinh mệt mỏi. Chuyển sang Local LLM (Phi-3) để phản xạ nhanh.{Style.RESET_ALL}")
            return self.local_llm.generate_text(prompt, temperature)

        config_params = {"temperature": temperature}
        if max_output_tokens:
            config_params["max_output_tokens"] = max_output_tokens
            
        contents = [prompt]
        if image_path:
            try:
                img = PIL.Image.open(image_path)
                contents.append(img)
            except Exception as e:
                logger.error(f"Lỗi nạp hình ảnh LLM: {e}")

        resp = self.client.models.generate_content(
            model=model_override or Config.MODEL_NAME, 
            contents=contents,
            config=types.GenerateContentConfig(**config_params)
        )
        return resp.text.strip()

    def generate_text(self, prompt: str, temperature: float = 0.7, model_override: str = None, max_output_tokens: int = None, image_path: str = None) -> str:
        prompt, max_output_tokens = self._apply_cognitive_throttling(prompt, max_output_tokens)
        try:
            return self._generate_text_with_retry(prompt, temperature, model_override, max_output_tokens, image_path=image_path)
        except Exception as e:
            logger.error(f"Lỗi LLM Text (đã retry 3 lần thất bại): {e}")
            return self.local_llm.generate_text(prompt, temperature)

    def generate_text_stream(self, prompt: str, temperature: float = 0.7, tools: list = None, model_override: str = None, max_output_tokens: int = None):
        prompt, max_output_tokens = self._apply_cognitive_throttling(prompt, max_output_tokens)
        if self._should_use_local(prompt) and not model_override:
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
