from google import genai
import os
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("API_KEY")
client = genai.Client(api_key=api_key)

print("=== TOÀN BỘ MODEL KHẢ DỤNG ===\n")
all_models = list(client.models.list())
all_models.sort(key=lambda m: m.name)
for m in all_models:
    print(f"{m.name}")
