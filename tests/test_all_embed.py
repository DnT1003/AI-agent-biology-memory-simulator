import requests
import os
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("API_KEY")

# Test ALL possible embedding model names that could output 3072
test_models = [
    "text-embedding-001",
    "text-embedding-004",
    "gemini-embedding-001",
    "embedding-001",
    "text-multilingual-embedding-002",
    "gemini-embedding-exp-03-07",
    "text-embedding-preview-0409",
]

print("=== TEST EMBEDDING MODELS ===")
for model in test_models:
    for version in ["v1", "v1beta"]:
        url = f"https://generativelanguage.googleapis.com/{version}/models/{model}:embedContent?key={api_key}"
        payload = {"model": f"models/{model}", "content": {"parts": [{"text": "test"}]}}
        r = requests.post(url, json=payload)
        if r.status_code == 200:
            dim = len(r.json()["embedding"]["values"])
            print(f"[{version}] {model} -> {dim} chieu !!!")
        else:
            code = r.status_code
            # Only print non-404s explicitly
            if code != 404:
                print(f"[{version}] {model} -> ERROR {code}: {r.json().get('error',{}).get('message','')[:60]}")
            else:
                print(f"[{version}] {model} -> 404")
