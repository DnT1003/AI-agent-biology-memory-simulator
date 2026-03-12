import requests
import os
from dotenv import load_dotenv

load_dotenv()
api_key_2 = os.getenv("API_KEY_2")
print(f"Đang test API_KEY_2: {api_key_2[:15]}...")

# Test text-embedding-004
url = f"https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:embedContent?key={api_key_2}"
payload = {
    "model": "models/text-embedding-004",
    "content": {
        "parts": [{"text": "test hello world"}]
    }
}

print("\n--- Test text-embedding-004 ---")
response = requests.post(url, json=payload)
if response.status_code == 200:
    embedding = response.json()["embedding"]["values"]
    print(f"✅ SUCCESS! text-embedding-004 hoạt động!")
    print(f"📐 Số chiều vector: {len(embedding)}")
else:
    print(f"❌ FAILED: {response.status_code}")
    print(response.json())

# Scan toàn bộ embedding models
print("\n--- Toàn bộ Embedding Models ---")
url2 = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key_2}&pageSize=200"
r2 = requests.get(url2)
if r2.status_code == 200:
    models = r2.json().get("models", [])
    print(f"Tổng số model: {len(models)}")
    for m in models:
        name = m.get("name", "")
        methods = m.get("supportedGenerationMethods", [])
        if "embedContent" in methods:
            print(f"  📌 {name}  [EMBEDDING]")
