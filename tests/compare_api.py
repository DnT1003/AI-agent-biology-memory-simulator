import requests
import sys

url = "http://localhost:8000/api/v2/tenants/default_tenant/databases/default_database/collections"

print(f"Testing URL: {url} on Python {sys.version}")
try:
    r = requests.get(url)
    print(f"Status: {r.status_code}")
    print(f"Response: {r.text}")
except Exception as e:
    print(f"Error: {e}")
