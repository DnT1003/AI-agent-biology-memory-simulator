import os
import sys
import requests

# Ensure project root on path
sys.path.insert(0, os.path.abspath(os.getcwd()))

from components.chroma_rest_client import ChromaRestClient

def test_rest():
    host = "localhost"
    port = 8000
    client = ChromaRestClient(host, port)
    
    col_name = "test_col_minimal"
    
    print(f"--- 1. Deleting collection: {col_name} ---")
    try:
        client.delete_collection(col_name)
    except Exception as e:
        print(f"Delete error (expected if missing): {e}")

    print(f"\n--- 2. Creating collection: {col_name} ---")
    col = client.get_or_create_collection(col_name)
    print(f"Collection ID: {col.id}")

    print(f"\n--- 3. Upserting into {col_name} ---")
    res = col.upsert(
        ids=["id1"], 
        embeddings=[[0.1]*1024], 
        metadatas=[{"meta": "data"}]
    )
    print(f"Upsert returned: {res}")

    print(f"\n--- 4. Querying {col_name} ---")
    q_res = col.query(
        query_embeddings=[[0.1]*1024],
        n_results=1
    )
    print(f"Query returned: {q_res}")

if __name__ == "__main__":
    try:
        test_rest()
        print("\nMINIMAL TEST: PASSED")
    except Exception as e:
        print(f"\nMINIMAL TEST: FAILED - {e}")
        import traceback
        traceback.print_exc()
