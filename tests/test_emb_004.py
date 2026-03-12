import requests
import os
from dotenv import load_dotenv

load_dotenv()

for key_name in ["API_KEY", "API_KEY_2"]:
    key = os.getenv(key_name)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:embedContent?key={key}"
    payload = {"model": "models/text-embedding-004", "content": {"parts": [{"text": "test"}]}}
    r = requests.post(url, json=payload)
    if r.status_code == 200:
        dim = len(r.json()["embedding"]["values"])
        print(f"[{key_name}] SUCCESS - {dim} chieu")
    else:
        err = r.json().get("error", {}).get("message", "unknown")[:100]
        print(f"[{key_name}] FAILED {r.status_code}: {err}")
