import requests

base = "http://localhost:8000/api/v2"

paths = [
    "heartbeat",
    "tenants",
    "databases",
    "tenants/default/databases/default/collections",
    "org/default/databases/default/collections",
    "collections"
]

print("Exploring ChromaDB v2 Search...")
for p in paths:
    url = f"{base}/{p}"
    try:
        r = requests.get(url)
        print(f"GET {url} -> {r.status_code}")
        if r.status_code == 200:
            print(f"  Response: {r.text[:200]}...")
    except Exception as e:
        print(f"GET {url} -> ERROR: {e}")
