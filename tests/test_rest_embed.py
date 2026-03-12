import requests
import os
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("API_KEY")

# Gọi REST API của Generative Language (generativelanguage.googleapis.com)
url = f"https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:embedContent?key={api_key}"
payload = {
    "model": "models/text-embedding-004",
    "content": {
        "parts": [{"text": "test hello world"}]
    }
}

response = requests.post(url, json=payload)
if response.status_code == 200:
    embedding = response.json()["embedding"]["values"]
    print(f"✅ SUCCESS! text-embedding-004 hoạt động!")
    print(f"📐 Số chiều vector: {len(embedding)}")
else:
    print(f"❌ FAILED: {response.status_code}")
    print(response.json())

# Kiểm tra luôn model list
print("\n=== MODEL LIST (generativelanguage.googleapis.com) ===")
url2 = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}&pageSize=100"
r2 = requests.get(url2)
if r2.status_code == 200:
    models = r2.json().get("models", [])
    for m in models:
        name = m.get("name", "")
        methods = m.get("supportedGenerationMethods", [])
        if "embedContent" in methods:
            print(f"  📌 {name}  [EMBEDDING]")
        elif "embed" in name.lower():
            print(f"  📌 {name}")
