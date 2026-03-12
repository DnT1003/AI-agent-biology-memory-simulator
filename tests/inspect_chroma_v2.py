import chromadb

client = chromadb.HttpClient(host='localhost', port=8000)

print(f"Client Default Tenant: {client.tenant}")
print(f"Client Default Database: {client.database}")

print("--- ChromaDB Collections Inspection ---")
try:
    cols = client.list_collections()
    print(f"Total Collections: {len(cols)}")
    for c in cols:
        print(f"\nName: {c.name}")
        print(f"ID: {c.id}")
        print(f"Metadata: {c.metadata}")
        # Trying to see tenant/db if available as attributes
        print(f"Tenant: {getattr(c, 'tenant', 'N/A')}")
        print(f"Database: {getattr(c, 'database', 'N/A')}")
except Exception as e:
    print(f"Error: {e}")
