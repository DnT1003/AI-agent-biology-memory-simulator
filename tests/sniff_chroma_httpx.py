import httpx
import chromadb
import sys

# Monkey-patch httpx
original_request = httpx.Client.request

def patched_request(self, method, url, **kwargs):
    print(f"DEBUG: {method} {url}")
    return original_request(self, method, url, **kwargs)

httpx.Client.request = patched_request

print(f"Testing HttpClient Calls (httpx) in Python {sys.version}")
client = chromadb.HttpClient(host='localhost', port=8000)
try:
    print("Call: heartbeat()")
    client.heartbeat()
    print("Call: list_collections()")
    client.list_collections()
except Exception as e:
    print(f"Error during calls: {e}")
