import requests

base = "http://localhost:8000/api/v2"

def fetch(url):
    print(f"GET {url}...")
    r = requests.get(url)
    print(f"  Status: {r.status_code}")
    if r.status_code == 200:
        return r.json()
    else:
        print(f"  Error Text: {r.text}")
        return None

print("--- Tenants ---")
tenants = fetch(f"{base}/tenants")
if tenants:
    for t in tenants:
        t_name = t['name']
        print(f"\n--- Databases for tenant '{t_name}' ---")
        dbs = fetch(f"{base}/tenants/{t_name}/databases")
        if dbs:
            for db in dbs:
                db_name = db['name']
                print(f"  --- Collections for tenant '{t_name}', db '{db_name}' ---")
                cols = fetch(f"{base}/tenants/{t_name}/databases/{db_name}/collections")
                if cols:
                    print(f"  {len(cols)} collections: {[c['name'] for c in cols]}")
