import os
import sys
import requests

# Ensure project root on path
sys.path.insert(0, os.path.abspath(os.getcwd()))

from components.chroma_rest_client import ChromaRestClient

def test_discovery():
    host = "127.0.0.1"
    port = 8000
    base = f"http://{host}:{port}/api/v2"
    
    variations = [
        ("default_tenant", "default_database"),
        ("default", "default"),
        ("", "default"),
        ("default", "")
    ]
    
    print(f"Testing on Python {sys.version}")
    
    for t, db in variations:
        url = f"{base}/tenants/{t}/databases/{db}/collections" if t and db else f"{base}/collections"
        print(f"\nTRYING: tenant='{t}', db='{db}' -> {url}")
        try:
            r = requests.get(url, timeout=2)
            print(f"  Status: {r.status_code}")
            if r.status_code == 200:
                cols = r.json()
                print(f"  Collections ({len(cols)} items): {[c['name'] for c in cols]}")
                for c in cols:
                    print(f"    - {c['name']}: ID={c['id']}")
        except Exception as e:
            print(f"  Error: {e}")

if __name__ == "__main__":
    test_discovery()
