from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import chromadb
import os

app = FastAPI(title="Aura ChromaDB Wrapper")

# Initialize ChromaDB Persistent Client
DB_PATH = os.getenv("CHROMA_DB_PATH", "outputs/chroma_db_server")
if not os.path.exists(DB_PATH):
    os.makedirs(DB_PATH)

print(f"Initializing ChromaDB Wrapper at {DB_PATH}")
client = chromadb.PersistentClient(path=DB_PATH)
collection = client.get_or_create_collection(
    name="aura_long_term_memory",
    metadata={"hnsw:space": "cosine"}
)

class AddRequest(BaseModel):
    ids: List[str]
    embeddings: Optional[List[List[float]]] = None
    metadatas: Optional[List[Dict[str, Any]]] = None
    documents: Optional[List[Optional[str]]] = None

class QueryRequest(BaseModel):
    query_embeddings: List[List[float]]
    n_results: int = 5
    where: Optional[Dict[str, Any]] = None
    include: Optional[List[str]] = ["metadatas", "distances"]

class GetRequest(BaseModel):
    limit: Optional[int] = None
    offset: Optional[int] = None
    where: Optional[Dict[str, Any]] = None
    include: Optional[List[str]] = ["metadatas"]

class DeleteRequest(BaseModel):
    ids: Optional[List[str]] = None
    where: Optional[Dict[str, Any]] = None

@app.post("/upsert")
async def upsert_memories(req: AddRequest):
    try:
        collection.upsert(
            ids=req.ids,
            embeddings=req.embeddings,
            metadatas=req.metadatas,
            documents=req.documents
        )
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/update")
async def update_memories(req: AddRequest):
    try:
        kwargs = {"ids": req.ids}
        if req.embeddings: kwargs["embeddings"] = req.embeddings
        if req.metadatas: kwargs["metadatas"] = req.metadatas
        if req.documents: kwargs["documents"] = req.documents
        collection.update(**kwargs)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/query")
async def query_memories(req: QueryRequest):
    try:
        results = collection.query(
            query_embeddings=req.query_embeddings,
            n_results=req.n_results,
            where=req.where,
            include=req.include
        )
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/get")
async def get_memories(req: GetRequest):
    try:
        kwargs = {}
        if req.limit is not None: kwargs["limit"] = req.limit
        if req.offset is not None: kwargs["offset"] = req.offset
        if req.where is not None: kwargs["where"] = req.where
        if req.include is not None: kwargs["include"] = req.include
        results = collection.get(**kwargs)
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/delete")
async def delete_memories(req: DeleteRequest):
    try:
        kwargs = {}
        if req.ids is not None: kwargs["ids"] = req.ids
        if req.where is not None: kwargs["where"] = req.where
        collection.delete(**kwargs)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/count")
async def count_memories():
    try:
        return {"count": collection.count()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/clear")
async def clear_all():
    global collection
    try:
        client.delete_collection("aura_long_term_memory")
        collection = client.get_or_create_collection(
            name="aura_long_term_memory",
            metadata={"hnsw:space": "cosine"}
        )
        return {"status": "success", "message": "Collection cleared."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health_check():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    # Allow passing custom port, default to 8000
    port = int(os.getenv("CHROMA_WRAPPER_PORT", 8000))
    uvicorn.run(app, host="127.0.0.1", port=port)
