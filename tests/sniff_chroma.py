import requests
import chromadb
import sys

# Monkey-patch requests
original_request = requests.Session.request

def patched_request(self, method, url, **kwargs):
    print(f"DEBUG: {method} {url}")
    return original_request(self, method, url, **kwargs)

requests.Session.request = patched_request

print(f"Testing HttpClient Calls in Python {sys.version}")
client = chromadb.HttpClient(host='localhost', port=8000)
try:
    print("Call: heartbeat()")
    client.heartbeat()
    print("Call: list_collections()")
    client.list_collections()
except Exception as e:
    print(f"Error during calls: {e}")
