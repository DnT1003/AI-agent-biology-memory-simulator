import httpx
import chromadb
import sys

# Monkey-patch httpx
original_request = httpx.Client.request

def patched_request(self, method, url, **kwargs):
    print(f"DEBUG_REST: {method} {url}")
    return original_request(self, method, url, **kwargs)

httpx.Client.request = patched_request

print(f"Testing Detailed HttpClient Calls (httpx) in Python {sys.version}")
client = chromadb.HttpClient(host='localhost', port=8000)
try:
    print("\n1. list_collections()")
    client.list_collections()
    
    col = client.get_or_create_collection("aura_long_term_memory")
    print(f"\n2. Collection found: {col.id}")
    
    print("\n3. upsert()")
    col.upsert(ids=["test_id"], embeddings=[[0.1]*10], metadatas=[{"test": True}], documents=["test doc"])
    
    print("\n4. query()")
    col.query(query_embeddings=[[0.1]*10], n_results=1)
    
except Exception as e:
    print(f"Error during calls: {e}")
