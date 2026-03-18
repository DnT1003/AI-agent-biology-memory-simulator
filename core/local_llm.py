import requests
import json
import logging
from config import Config

logger = logging.getLogger(__name__)

class LocalLLM:
    """Wrapper cho Ollama API chạy tại local"""
    def __init__(self):
        self.url = Config.OLLAMA_URL
        self.model = Config.LOCAL_MODEL_NAME

    def generate_text(self, prompt: str, temperature: float = 0.7, top_p: float = 1.0, top_k: int = 40, aura_state: dict = None) -> tuple[str, float]:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "top_p": top_p,
                "top_k": top_k
            }
        }
        if aura_state:
            payload["aura_state"] = aura_state

        try:
            response = requests.post(f"{self.url}/generate", json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
            return data.get("response", "").strip(), data.get("entropy", 0.0)
        except Exception as e:
            logger.error(f"Lỗi Local LLM Text (Ollama): {e}")
            return "", 0.0

    def generate_json(self, prompt: str, temperature: float = 0.1, top_p: float = 1.0, top_k: int = 40, aura_state: dict = None) -> tuple[dict, float]:
        """Ép Ollama trả về JSON (Phi-3 hỗ trợ tốt format này)"""
        json_prompt = f"{prompt}\n\nIMPORTANT: Return ONLY a valid JSON object. Do not include any explanation or markdown backticks outside the JSON."
        
        payload = {
            "model": self.model,
            "prompt": json_prompt,
            "format": "json",
            "stream": False,
            "options": {
                "temperature": temperature,
                "top_p": top_p,
                "top_k": top_k
            }
        }
        if aura_state:
            payload["aura_state"] = aura_state

        try:
            response = requests.post(f"{self.url}/generate", json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
            res_text = data.get("response", "{}")
            return json.loads(res_text), data.get("entropy", 0.0)
        except Exception as e:
            logger.error(f"Lỗi Local LLM JSON (Ollama): {e}")
            return {}, 0.0

    def generate_text_stream(self, prompt: str, temperature: float = 0.7, top_p: float = 1.0, top_k: int = 40, aura_state: dict = None):
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": True,
            "options": {
                "temperature": temperature,
                "top_p": top_p,
                "top_k": top_k
            }
        }
        if aura_state:
            payload["aura_state"] = aura_state

        try:
            response = requests.post(f"{self.url}/generate", json=payload, stream=True, timeout=60)
            response.raise_for_status()
            for line in response.iter_lines():
                if line:
                    chunk = json.loads(line.decode("utf-8"))
                    yield chunk.get("response", ""), chunk.get("entropy", 0.0)
                    if chunk.get("done"):
                        break
        except Exception as e:
            logger.error(f"Lỗi Local LLM Stream (Ollama): {e}")
