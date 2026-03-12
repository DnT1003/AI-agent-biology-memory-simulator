import chromadb
import sys

print(f"Verifying ChromaDB with Python {sys.version}")
try:
    client = chromadb.HttpClient(host='localhost', port=8000)
    heartbeat = client.heartbeat()
    print(f"Heartbeat: {heartbeat}")
    collections = client.list_collections()
    print(f"Collections: {len(collections)}")
    for col in collections:
        print(f" - {col.name}")
    print("Verification: PASSED")
except Exception as e:
    print(f"Verification: FAILED - {e}")
