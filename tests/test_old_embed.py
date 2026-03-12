import google.generativeai as genai
import os
from dotenv import load_dotenv

load_dotenv()
genai.configure(api_key=os.getenv("API_KEY"))

try:
    result = genai.embed_content(
        model="models/text-embedding-004",
        content="test hello world"
    )
    dim = len(result["embedding"])
    print(f"SUCCESS! text-embedding-004 hoạt động!")
    print(f"Số chiều vector: {dim}")
except Exception as e:
    print(f"FAILED: {e}")

# List all embedding models available
print("\n=== EMBEDDING MODELS (google-generativeai) ===")
for m in genai.list_models():
    if "embedContent" in [a for a in (m.supported_generation_methods or [])]:
        print(f"  {m.name}")
