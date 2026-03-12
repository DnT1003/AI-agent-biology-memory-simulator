import chromadb
import json

client = chromadb.PersistentClient(path="outputs/chroma_db")
col = client.get_collection("aura_long_term_memory")
results = col.peek(limit=3)

for i, meta in enumerate(results["metadatas"]):
    data = json.loads(meta["data"])
    content = data.get("content", "")[:80]
    mtype = data.get("type")
    valence = data.get("valence")
    arousal = data.get("arousal")
    print(f"=== Memory {i+1} ===")
    print(f"  content: {content}...")
    print(f"  type: {mtype}, valence: {valence}, arousal: {arousal}")
    if results["embeddings"] is not None and len(results["embeddings"]) > 0:
        dim = len(results["embeddings"][i])
        print(f"  vector dim: {dim}")
