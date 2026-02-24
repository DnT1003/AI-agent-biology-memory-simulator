# LLM Component wrapper cho Google GenAI
import json
from google import genai
from google.genai import types
from config import Config

class LLM:
    def __init__(self):
        self.client = genai.Client(api_key=Config.API_KEY)

    def generate_json(self, prompt: str, temperature: float = 0.1) -> dict:
        try:
            resp = self.client.models.generate_content(
                model=Config.MODEL_NAME, 
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json", temperature=temperature)
            )
            data = json.loads(resp.text)

            if isinstance(data, list):
                if len(data) > 0:
                    return data[0]
                else:
                    return {}
            return data

        except Exception as e:
            print(f"⚠️ Lỗi LLM JSON: {e}")
            return {}

    def generate_text(self, prompt: str, temperature: float = 0.7) -> str:
        try:
            resp = self.client.models.generate_content(
                model=Config.MODEL_NAME, 
                contents=prompt,
                config=types.GenerateContentConfig(temperature=temperature)
            )
            return resp.text.strip()
        except Exception as e:
            print(f"⚠️ Lỗi LLM Text: {e}")
            return ""

    def generate_text_stream(self, prompt: str, temperature: float = 0.7):
        try:
            responses = self.client.models.generate_content_stream(
                model=Config.MODEL_NAME, 
                contents=prompt,
                config=types.GenerateContentConfig(temperature=temperature)
            )
            for chunk in responses:
                if chunk.text:
                    yield chunk.text
        except Exception as e:
            print(f"⚠️ Lỗi LLM Stream: {e}")
