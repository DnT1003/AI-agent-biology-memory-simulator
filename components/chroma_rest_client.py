import requests
import json
from typing import List, Dict, Any, Optional

class ChromaRestClient:
    """A minimal REST client for ChromaDB to bypass Pydantic v1 issues in Python 3.14."""
    def __init__(self, host: str, port: int, tenant: str = "default_tenant", database: str = "default_database"):
        self.base_url = f"http://{host}:{port}/api/v2"
        self.tenant_db_path = f"tenants/{tenant}/databases/{database}"
        self._collections_cache = {}

    def _request(self, method, endpoint, ignore_404=False, **kwargs):
        # If endpoint doesn't start with 'heartbeat', prefix it with tenant/db path
        if endpoint != "heartbeat" and not endpoint.startswith("tenants/"):
            url = f"{self.base_url}/{self.tenant_db_path}/{endpoint}"
        elif endpoint.startswith("tenants/"):
             url = f"{self.base_url}/{endpoint}"
        else:
            url = f"{self.base_url}/{endpoint}"
            
        resp = requests.request(method, url, timeout=kwargs.pop('timeout', 10), **kwargs)
        
        if resp.status_code == 404 and ignore_404:
            return {}
        if resp.status_code >= 400:
            print(f"[ERROR] [CHROMA REST]: {method} {url} failed with {resp.status_code}: {resp.text}")
        resp.raise_for_status()
        return resp.json()

    def heartbeat(self):
        return self._request("GET", "heartbeat")

    def list_collections(self):
        cols = self._request("GET", "collections")
        # print(f"[INFO] [CHROMA REST]: Collections list ({len(cols)} items): {[c['name'] for c in cols]}")
        return cols

    def delete_collection(self, name: str):
        # print(f"[INFO] [CHROMA REST]: Deleting collection '{name}'...")
        return self._request("DELETE", f"collections/{name}", ignore_404=True)

    def get_or_create_collection(self, name: str, metadata: Optional[Dict] = None):
        # 1. Force refresh collection list
        collections = self.list_collections()
        for col in collections:
            if col['name'] == name:
                return CollectionWrapper(self, col['id'], col['name'])
        
        # 2. Create if not found
        try:
            resp_data = self._request("POST", "collections", json={
                "name": name,
                "metadata": metadata or {}
            })
            return CollectionWrapper(self, resp_data['id'], resp_data['name'])
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 400 and "already exists" in e.response.text:
                # Race condition: created elsewhere or just now. Re-fetch.
                collections = self.list_collections()
                for col in collections:
                    if col['name'] == name:
                        return CollectionWrapper(self, col['id'], col['name'])
            raise e

class CollectionWrapper:
    def __init__(self, client, id: str, name: str):
        self.client = client
        self.id = id
        self.name = name

    def upsert(self, ids: List[str], embeddings: List[List[float]], metadatas: List[Dict]):
        # The endpoint expects the data in the body
        payload = {
            "ids": ids,
            "embeddings": embeddings,
            "metadatas": metadatas,
            "documents": [None] * len(ids) # Chroma requires documents or None
        }
        return self.client._request("POST", f"collections/{self.id}/upsert", json=payload)

    def update(self, ids: List[str], embeddings: Optional[List[List[float]]] = None, metadatas: Optional[List[Dict]] = None):
        payload = {"ids": ids}
        if embeddings: payload["embeddings"] = embeddings
        if metadatas: payload["metadatas"] = metadatas
        return self.client._request("POST", f"collections/{self.id}/update", json=payload)

    def query(self, query_embeddings: List[List[float]], n_results: int = 5, where: Optional[Dict] = None, include: List[str] = None):
        payload = {
            "query_embeddings": query_embeddings,
            "n_results": n_results,
            "where": where or {},
            "include": include or ["metadatas", "distances"]
        }
        return self.client._request("POST", f"collections/{self.id}/query", json=payload)

    def get(self, where: Optional[Dict] = None, limit: Optional[int] = None, offset: Optional[int] = None, include: List[str] = None):
        payload = {
            "where": where or {},
            "include": include or ["metadatas"]
        }
        if limit: payload["limit"] = limit
        if offset: payload["offset"] = offset
        return self.client._request("POST", f"collections/{self.id}/get", json=payload)

    def delete(self, ids: Optional[List[str]] = None, where: Optional[Dict] = None):
        payload = {}
        if ids: payload["ids"] = ids
        if where: payload["where"] = where
        return self.client._request("POST", f"collections/{self.id}/delete", json=payload)

    def count(self):
        resp = requests.get(f"{self.client.base_url}/collections/{self.id}/count", timeout=10)
        resp.raise_for_status()
        return int(resp.text)
