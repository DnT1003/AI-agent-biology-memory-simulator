import sys
import os
import json
from colorama import Fore, Style

# Ensure the project root is in sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from components.vector_store import VectorStore
from components.embedder import Embedder
from config import Config
from core.memory import MemoryTrace, memory_type_from_str
from core.writer_lease import ProcessWriterLease

def migrate():
    with ProcessWriterLease(Config.MEMORY_WRITER_LEASE_FILE):
        return _migrate_locked()


def _migrate_locked():
    import chromadb

    print(f"{Fore.CYAN}--- BEGIN DB MIGRATION TO V4 (1024D & FLAT METADATA) ---{Style.RESET_ALL}")
    db_path = Config.CHROMA_DB_PATH
    if not os.path.exists(db_path):
        print("Database path does not exist. No migration needed.")
        return

    client = chromadb.PersistentClient(path=db_path)
    try:
        collection = client.get_collection(name="aura_long_term_memory")
    except Exception:
        print("Collection 'aura_long_term_memory' not found. No migration needed.")
        return

    results = collection.get(include=["metadatas"])
    if not results or not results.get('metadatas'):
        print("Empty collection. Nothing to migrate.")
        return
        
    metadatas = results['metadatas']
    if metadatas and metadatas[0].get('schema_version') == '4':
        print("DB is already using schema_version v4. No migration needed.")
        return

    print(f"Found {len(metadatas)} items in old DB to migrate.")
    memories = []
    
    for meta in metadatas:
        try:
            if "data" in meta:
                data = json.loads(meta["data"])
                
                # Convert type to enum
                if "type" in data:
                    data["type"] = memory_type_from_str(data["type"])
                    
                known_fields = {f.name for f in MemoryTrace.__dataclass_fields__.values()}
                data = {k: v for k, v in data.items() if k in known_fields}
                memories.append(MemoryTrace(**data))
            else:
                # If already somewhat flat but lacking, try to reconstruct
                data = meta.copy()
                if "schema_version" in data: del data["schema_version"]
                if "overlays" in data and isinstance(data["overlays"], str):
                    data["overlays"] = data["overlays"].split("\n||\n") if data["overlays"] else []
                if "is_flashbulb" in data: data["is_flashbulb"] = bool(data["is_flashbulb"])
                if "type" in data:
                    data["type"] = memory_type_from_str(data["type"])
                    
                known_fields = {f.name for f in MemoryTrace.__dataclass_fields__.values()}
                data = {k: v for k, v in data.items() if k in known_fields}
                memories.append(MemoryTrace(**data))
                
        except Exception as e:
            print(f"{Fore.RED}Skipping malformed memory: {e}{Style.RESET_ALL}")

    print(f"{Fore.GREEN}Successfully parsed {len(memories)} memory traces.{Style.RESET_ALL}")
    
    if len(memories) == 0:
        print("No valid memories parsed. Aborting migration.")
        return
        
    print(f"{Fore.YELLOW}Deleting old collection to reset dimension space (3072D -> 1024D)...{Style.RESET_ALL}")
    client.delete_collection(name="aura_long_term_memory")
    
    print("Initializing new VectorStore and Embedder...")
    embedder = Embedder()
    store = VectorStore()
    
    print(f"Re-embedding and saving {len(memories)} memories...")
    
    batch_size = 50
    for i in range(0, len(memories), batch_size):
        batch = memories[i:i+batch_size]
        texts = [m.content for m in batch]
        
        try:
            vectors = embedder.encode(texts)
            ids = [m.id for m in batch]
            store.add_batch(ids, vectors, batch)
            print(f"{Fore.CYAN}Migrated {i + len(batch)} / {len(memories)}{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.RED}Failed to migrate batch starting at {i}: {e}{Style.RESET_ALL}")
            
    print(f"{Fore.GREEN}--- MIGRATION COMPLETE ---{Style.RESET_ALL}")

if __name__ == "__main__":
    migrate()
