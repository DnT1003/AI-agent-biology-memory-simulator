import requests
import os
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("API_KEY")

# Test gemini-embedding-001 with outputDimensionality parameter
print("=== TEST gemini-embedding-001 with outputDimensionality ===")

for dim in [768, 1024, 2048, 3072]:
    url = f"https://generativelanguage.googleapis.com/v1/models/gemini-embedding-001:embedContent?key={api_key}"
    payload = {
        "model": "models/gemini-embedding-001",
        "content": {"parts": [{"text": "test hello world"}]},
        "outputDimensionality": dim
    }
    r = requests.post(url, json=payload)
    if r.status_code == 200:
        actual_dim = len(r.json()["embedding"]["values"])
        print(f"  Requested {dim} -> Got {actual_dim} !")
    else:
        msg = r.json().get("error", {}).get("message", "")[:80]
        print(f"  Requested {dim} -> Error {r.status_code}: {msg}")

# Also test text-embedding-004 with outputDimensionality
print("\n=== TEST text-embedding-004 with outputDimensionality ===")
for dim in [768, 3072]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:embedContent?key={api_key}"
    payload = {
        "model": "models/text-embedding-004",
        "content": {"parts": [{"text": "test hello world"}]},
        "outputDimensionality": dim
    }
    r = requests.post(url, json=payload)
    if r.status_code == 200:
        actual_dim = len(r.json()["embedding"]["values"])
        print(f"  Requested {dim} -> Got {actual_dim} !")
    else:
        msg = r.json().get("error", {}).get("message", "")[:80]
        print(f"  Requested {dim} -> Error {r.status_code}: {msg}")
