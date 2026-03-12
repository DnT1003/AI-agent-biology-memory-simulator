import sys
import os

print(f"Testing on Python {sys.version}")

try:
    print("\n1. Testing Google Embedder...")
    sys.path.insert(0, os.path.abspath(os.getcwd()))
    from components.embedder import Embedder
    embedder = Embedder()
    vec = embedder.encode("test")
    print("Google Embedder: OK")
except Exception as e:
    print(f"Google Embedder: FAILED - {e}")
    import traceback
    traceback.print_exc()

try:
    print("\n2. Testing Chroma REST Heartbeat...")
    import requests
    resp = requests.get("http://localhost:8000/api/v1/heartbeat")
    print(f"Chroma Heartbeat: {resp.status_code} - {resp.json()}")
except Exception as e:
    print(f"Chroma Heartbeat: FAILED - {e}")
