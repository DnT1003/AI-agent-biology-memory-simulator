
import chromadb
import os

def inspect_db():
    db_path = "outputs/chroma_db"
    if not os.path.exists(db_path):
        print(f"Directory {db_path} does not exist.")
        return

    client = chromadb.PersistentClient(path=db_path)
    collections = client.list_collections()
    print(f"Found {len(collections)} collections.")
    for col in collections:
        print(f"\nCollection: {col.name}")
        print(f"Metadata: {col.metadata}")
        count = col.count()
        print(f"Entry Count: {count}")
        if count > 0:
            sample = col.peek(limit=1)
            embeddings = sample.get('embeddings')
            if embeddings is not None and len(embeddings) > 0:
                dim = len(embeddings[0])
                print(f"Embedding Dimension: {dim}")
            else:
                print("No embeddings found in sample metadata.")

if __name__ == "__main__":
    inspect_db()
