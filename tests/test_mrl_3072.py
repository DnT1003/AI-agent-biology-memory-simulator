import requests
import os
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("API_KEY")
api_key_2 = os.getenv("API_KEY_2")

# text-embedding-004 supports MRL with outputDimensionality up to 3072
# Test all combinations of endpoints and keys
print("=== TEST text-embedding-004 with outputDimensionality=3072 (MRL) ===\n")

endpoints = [
    ("v1", f"https://generativelanguage.googleapis.com/v1/models/text-embedding-004:embedContent"),
    ("v1beta", f"https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:embedContent"),
]

for key_name, key in [("API_KEY", api_key), ("API_KEY_2", api_key_2)]:
    for version, base_url in endpoints:
        url = f"{base_url}?key={key}"
        payload = {
            "model": "models/text-embedding-004",
            "content": {"parts": [{"text": "test hello world"}]},
            "outputDimensionality": 3072
        }
        r = requests.post(url, json=payload)
        if r.status_code == 200:
            dim = len(r.json()["embedding"]["values"])
            print(f"[{key_name}][{version}] SUCCESS! Dim = {dim}")
        else:
            msg = r.json().get("error", {}).get("message", "")[:70]
            print(f"[{key_name}][{version}] {r.status_code}: {msg}")

# Also check if gemini-embedding-001 supports MRL to 3072  
print("\n=== TEST gemini-embedding-001 với outputDimensionality=3072 (v1beta) ===")
url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:embedContent?key={api_key}"
payload = {
    "model": "models/gemini-embedding-001",
    "content": {"parts": [{"text": "test hello world"}]},
    "outputDimensionality": 3072
}
r = requests.post(url, json=payload)
if r.status_code == 200:
    dim = len(r.json()["embedding"]["values"])
    print(f"SUCCESS! outputDimensionality=3072 -> got {dim} dim")
else:
    msg = r.json().get("error", {}).get("message", "")[:100]
    print(f"FAILED {r.status_code}: {msg}")
