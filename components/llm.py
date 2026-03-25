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
try:
    import PIL.Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

class LLM:
    def __init__(self, ego=None):
        from core.settings_manager import settings_manager
        self.settings = settings_manager
        
        # We initialize Gemini client lazily or update later if needed
        api_key = self.settings.get("gemini_api_key", Config.API_KEY)
        self.client = genai.Client(api_key=api_key) if api_key else None
        
        self.local_llm = LocalLLM()
        self.ego = ego # Tham chiếu tới SelfModel để check Fatigue

    def _should_use_local(self, prompt: str = "") -> bool:
        """Quyết định dùng Local LLM dựa trên: Config, Fatigue, lệnh đặc thù hoặc settings"""
        provider = self.settings.get("provider", "local")
        
        if provider == "local":
            return True
            
        # Kiểm tra lệnh đặc thù ép dùng local
        if prompt and any(cmd in prompt.lower() for cmd in getattr(Config, 'FORCE_LOCAL_COMMANDS', [])):
            return True
            
        if self.ego and getattr(self.ego, 'fatigue', 0.0) > 0.7:
            return True
        return False

    def _apply_cognitive_throttling(self, prompt: str, temperature: float = 0.7, max_output_tokens: int = None) -> tuple:
        """[Phase 24] Điều tiết động các tham số (Temp, Top_P, Tokens) dựa trên sinh lý."""
        params = {
            "temperature": temperature,
            "top_p": 1.0,
            "max_output_tokens": max_output_tokens
        }
        
        if not self.ego:
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
        retry=retry_if_exception_type(Exception),
        reraise=True
    )
    def _generate_json_with_retry(self, prompt: str, temperature: float, top_p: float = 1.0, model_override: str = None, max_output_tokens: int = None, force_local: bool = False, image_path: str = None) -> tuple:
        provider = self.settings.get("provider", "local")
        
        if (self._should_use_local(prompt) or force_local or provider == "local") and not model_override:
            if image_path:
                print(f"{Fore.YELLOW}⚠️ [HYBRID LLM]: Local LLM (Phi-3) không hỗ trợ Vision. Bỏ qua hình ảnh.{Style.RESET_ALL}")
            print(f"{Fore.LIGHTBLACK_EX}⚡ [HYBRID LLM]: {'Force Local' if force_local else 'Hệ thần kinh mệt mỏi/Thiết lập Local'}. Sử dụng Local LLM.{Style.RESET_ALL}")
            return self.local_llm.generate_json(prompt, temperature, top_p=top_p)

        if provider == "openai":
            import requests
            api_key = self.settings.get("openai_api_key", "")
            if not api_key: return {}
            model = model_override or self.settings.get("openai_model", "gpt-4o-mini")
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            payload = {
                "model": model,
                "messages": [{"role": "system", "content": "You are a helpful assistant. Please output ONLY valid JSON without any markdown formatting or comments."}, {"role": "user", "content": prompt}],
                "temperature": temperature,
                "top_p": top_p,
                "response_format": { "type": "json_object" }
            }
            if max_output_tokens: payload["max_tokens"] = max_output_tokens
            response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=60)
            response.raise_for_status()
            text = response.json()["choices"][0]["message"]["content"]
            try: return json.loads(text), 0.0
            except: return {}, 0.0

        elif provider == "anthropic":
            import requests
            api_key = self.settings.get("anthropic_api_key", "")
            if not api_key: return {}
            model = model_override or self.settings.get("anthropic_model", "claude-3-haiku-20240307")
            headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": prompt + "\n\nImportant: Output ONLY valid JSON."}],
                "temperature": temperature,
                "max_tokens": max_output_tokens or 2048,
            }
            response = requests.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload, timeout=60)
            response.raise_for_status()
            text = response.json()["content"][0]["text"]
            try: return json.loads(text), 0.0
            except: return {}, 0.0

        # Default to Gemini
        gemini_model = model_override or self.settings.get("gemini_model", Config.MODEL_NAME)
        config_params = {"response_mime_type": "application/json", "temperature": temperature, "top_p": top_p}
        if max_output_tokens:
            config_params["max_output_tokens"] = max_output_tokens
            
        contents = [prompt]
        if image_path:
            if not HAS_PIL:
                logger.warning(f"Không thể nạp hình ảnh vì chưa cài đặt module Pillow: {image_path}")
                print(f"{Fore.YELLOW}⚠️ [HỆ THỐNG]: Cần cài đặt Pillow để nhận dạng ảnh. Vui lòng chạy: pip install Pillow.{Style.RESET_ALL}")
            else:
                try:
                    img = PIL.Image.open(image_path)
                    contents.append(img)
                except Exception as e:
                    logger.error(f"Lỗi nạp hình ảnh LLM: {e}")

        if not self.client:
           self.client = genai.Client(api_key=self.settings.get("gemini_api_key", Config.API_KEY))
           
        resp = self.client.models.generate_content(
            model=gemini_model, 
            contents=contents,
            config=types.GenerateContentConfig(**config_params)
        )
        
        # Robust JSON extraction
        text = resp.text.strip()
        try:
            # Try direct load first
            data = json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON block in markdown
            import re
            json_match = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
            if json_match:
                try:
                    data = json.loads(json_match.group(1))
                except json.JSONDecodeError:
                    data = {}
            else:
                # Last resort: find first { and last }
                start = text.find('{')
                end = text.rfind('}')
                if start != -1 and end != -1:
                    try:
                        data = json.loads(text[start:end+1])
                    except json.JSONDecodeError:
                        data = {}
                else:
                    data = {}

        if isinstance(data, list):
            return (data[0] if len(data) > 0 else {}), 0.0
        return data, 0.0

    def generate_json(self, prompt: str, temperature: float = 0.1, model_override: str = None, max_output_tokens: int = None, force_local: bool = False, image_path: str = None) -> tuple:
        prompt, p = self._apply_cognitive_throttling(prompt, temperature, max_output_tokens)
        try:
            return self._generate_json_with_retry(prompt, p["temperature"], p["top_p"], model_override, p["max_output_tokens"], force_local=force_local, image_path=image_path)
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
    def _generate_text_with_retry(self, prompt: str, temperature: float, top_p: float = 1.0, model_override: str = None, max_output_tokens: int = None, image_path: str = None) -> tuple:
        provider = self.settings.get("provider", "local")
        if (self._should_use_local(prompt) or provider == "local") and not model_override:
            if image_path:
                print(f"{Fore.YELLOW}⚠️ [HYBRID LLM]: Local LLM (Phi-3) không hỗ trợ Vision. Bỏ qua hình ảnh.{Style.RESET_ALL}")
            print(f"{Fore.LIGHTBLACK_EX}⚡ [HYBRID LLM]: Hệ thần kinh mệt mỏi/Thiết lập Local. Chuyển sang Local LLM.{Style.RESET_ALL}")
            return self.local_llm.generate_text(prompt, temperature, top_p=top_p)

        if provider == "openai":
            import requests
            api_key = self.settings.get("openai_api_key", "")
            if not api_key: return ""
            model = model_override or self.settings.get("openai_model", "gpt-4o-mini")
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            payload = {
                "model": model,
                "messages": [{"role": "system", "content": "You are a helpful assistant."}, {"role": "user", "content": prompt}],
                "temperature": temperature,
                "top_p": top_p,
            }
            if max_output_tokens: payload["max_tokens"] = max_output_tokens
            response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=60)
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"], 0.0

        elif provider == "anthropic":
            import requests
            api_key = self.settings.get("anthropic_api_key", "")
            if not api_key: return ""
            model = model_override or self.settings.get("anthropic_model", "claude-3-haiku-20240307")
            headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
                "max_tokens": max_output_tokens or 2048,
            }
            response = requests.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload, timeout=60)
            response.raise_for_status()
            return response.json()["content"][0]["text"], 0.0

        # Default back to Gemini
        gemini_model = model_override or self.settings.get("gemini_model", Config.MODEL_NAME)
        config_params = {"temperature": temperature, "top_p": top_p}
        if max_output_tokens:
            config_params["max_output_tokens"] = max_output_tokens
            
        contents = [prompt]
        if image_path:
            if not HAS_PIL:
                logger.warning(f"Không thể nạp hình ảnh vì chưa cài đặt module Pillow: {image_path}")
                print(f"{Fore.YELLOW}⚠️ [HỆ THỐNG]: Cần cài đặt Pillow để nhận dạng ảnh. Vui lòng chạy: pip install Pillow.{Style.RESET_ALL}")
            else:
                try:
                    img = PIL.Image.open(image_path)
                    contents.append(img)
                except Exception as e:
                    logger.error(f"Lỗi nạp hình ảnh LLM: {e}")

        if not self.client:
           self.client = genai.Client(api_key=self.settings.get("gemini_api_key", Config.API_KEY))

        resp = self.client.models.generate_content(
            model=gemini_model, 
            contents=contents,
            config=types.GenerateContentConfig(**config_params)
        )
        return resp.text.strip(), 0.0

    def generate_text(self, prompt: str, temperature: float = 0.7, model_override: str = None, max_output_tokens: int = None, image_path: str = None) -> tuple:
        prompt, p = self._apply_cognitive_throttling(prompt, temperature, max_output_tokens)
        try:
            return self._generate_text_with_retry(prompt, p["temperature"], p["top_p"], model_override, p["max_output_tokens"], image_path=image_path)
        except Exception as e:
            logger.error(f"Lỗi LLM Text (đã retry 3 lần thất bại): {e}")
            return self.local_llm.generate_text(prompt, temperature)

    def generate_text_stream(self, prompt: str, temperature: float = 0.7, tools: list = None, model_override: str = None, max_output_tokens: int = None):
        prompt, p = self._apply_cognitive_throttling(prompt, temperature, max_output_tokens)
        if self._should_use_local(prompt) and not model_override:
            yield from self.local_llm.generate_text_stream(prompt, p["temperature"], top_p=p["top_p"])
            return

        try:
            config_params = {"temperature": p["temperature"], "top_p": p["top_p"]}
            if p["max_output_tokens"]:
                config_params["max_output_tokens"] = p["max_output_tokens"]
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
