import os
import json
import numpy as np
import requests
from typing import List, Tuple, Any, Dict, Optional
from colorama import Fore, Style
from core.logger import get_logger

logger = get_logger("vector_store")
LIFTED_FIELDS = {"type", "valence", "importance", "strength", "is_flashbulb"}

from components.chroma_rest_client import ChromaRestClient

class VectorStore:
    def __init__(self):
        from config import Config
        import sys
        
        is_py314 = sys.version_info.major == 3 and sys.version_info.minor == 14

        if Config.USE_CHROMA_SERVER or is_py314:
            if is_py314:
                print(f"{Fore.YELLOW}🐍 [VECTOR STORE]: Python 3.14 detected. Switching to ChromaRestClient (REST Mode) to avoid Pydantic v1 issues.{Style.RESET_ALL}")
            
            print(f"{Fore.CYAN}🌐 [VECTOR STORE]: Connecting to Chroma Server at {Config.CHROMA_SERVER_HOST}:{Config.CHROMA_SERVER_PORT}...{Style.RESET_ALL}")
            self.client = ChromaRestClient(host=Config.CHROMA_SERVER_HOST, port=Config.CHROMA_SERVER_PORT)
        else:
            try:
                import chromadb
                db_path = getattr(Config, 'CHROMA_DB_PATH', "outputs/chroma_db")
                if not os.path.exists(db_path):
                    os.makedirs(db_path)
                self.client = chromadb.PersistentClient(path=db_path)
            except ImportError:
                print(f"{Fore.RED}❌ [VECTOR STORE]: chromadb not installed. Please use USE_CHROMA_SERVER=True or install it.{Style.RESET_ALL}")
                raise

        try:
            self.collection = self.client.get_or_create_collection(
                name="aura_long_term_memory",
                metadata={"hnsw:space": "cosine"}
            )
        except Exception as e:
            print(f"{Fore.RED}⚠️ [VECTOR STORE]: Could not connect to Chroma Server: {e}{Style.RESET_ALL}")
            # Mock collection to allow system to start without crashing
            self.collection = type('MockCollection', (), {
                'upsert': lambda self, *args, **kwargs: None,
                'update': lambda self, *args, **kwargs: None,
                'delete': lambda self, *args, **kwargs: None,
                'get': lambda self, *args, **kwargs: {'ids': [], 'metadatas': []},
                'query': lambda self, *args, **kwargs: {'ids': [[]], 'metadatas': [[]], 'distances': [[]]},
                'count': lambda self, *args, **kwargs: 0
            })()

    # ─────────────────────────────────────────────────
    # INTERNAL SERIALIZATION / DESERIALIZATION
    # ─────────────────────────────────────────────────

    def _obj_to_dict(self, obj: Any) -> dict:
        """Phase 17B: Metadata Flattening - DB Optimization. Không dùng json.dumps."""
        raw = obj.__dict__.copy()
        meta = {
            "schema_version": "4",
            "timestamp": float(getattr(obj, 'created_at', 0.0))
        }
        for k, v in raw.items():
            if v is None: continue
            if isinstance(v, bool):
                meta[k] = int(v)
            elif isinstance(v, (int, float, str)):
                meta[k] = v
            elif isinstance(v, list):
                if k == "overlays":
                    meta[k] = "\n||\n".join(v)
                else:
                    meta[k] = str(v)
            else:
                meta[k] = str(v)
        return meta

    def _dict_to_obj(self, metadata_dict: dict) -> Any:
        """Phục hồi Object từ metadata phẳng."""
        from core.memory import MemoryTrace
        try:
            if metadata_dict.get("schema_version") in ["1", "2", "3"] and "data" in metadata_dict:
                data = json.loads(metadata_dict["data"])
            else:
                data = metadata_dict.copy()
                if "schema_version" in data: del data["schema_version"]
                if "overlays" in data and isinstance(data["overlays"], str):
                    data["overlays"] = data["overlays"].split("\n||\n") if data["overlays"] else []
                if "is_flashbulb" in data: data["is_flashbulb"] = bool(data["is_flashbulb"])
                if "type" in data:
                    from core.memory import memory_type_from_str
                    data["type"] = memory_type_from_str(data["type"])
                    
            known_fields = {f.name for f in MemoryTrace.__dataclass_fields__.values()}
            data = {k: v for k, v in data.items() if k in known_fields}
            return MemoryTrace(**data)
        except Exception:
            logger.error("Failed to deserialize MemoryTrace", exc_info=True)
            return None

    # ─────────────────────────────────────────────────
    # WRITE OPERATIONS
    # ─────────────────────────────────────────────────

    def add(self, record_id: str, vector, meta: Any):
        try:
            vec = vector.tolist() if isinstance(vector, np.ndarray) else list(vector)
            self.collection.upsert(
                ids=[record_id],
                embeddings=[vec],
                metadatas=[self._obj_to_dict(meta)]
            )
        except Exception:
            logger.error(f"Failed to upsert vector {record_id}", exc_info=True)

    def add_batch(self, record_ids: List[str], vectors, metas: List[Any]):
        """Batch upsert tối ưu cho tốc độ khi nạp data lớn."""
        try:
            self.collection.upsert(
                ids=record_ids,
                embeddings=[v.tolist() if isinstance(v, np.ndarray) else list(v) for v in vectors],
                metadatas=[self._obj_to_dict(m) for m in metas]
            )
        except Exception:
            logger.error(f"Failed to upsert batch of {len(record_ids)} vectors", exc_info=True)

    def update_meta(self, record_id: str, meta: Any):
        try:
            self.collection.update(
                ids=[record_id],
                metadatas=[self._obj_to_dict(meta)]
            )
        except Exception:
            logger.error(f"Failed to update_meta for {record_id}", exc_info=True)

    def update_vector(self, record_id: str, vector: np.ndarray):
        try:
            self.collection.update(
                ids=[record_id],
                embeddings=[vector.tolist()]
            )
        except Exception:
            logger.error(f"Failed to update_vector for {record_id}", exc_info=True)

    def remove(self, record_id: str):
        self.collection.delete(ids=[record_id])

    def delete_weak_memories(self, threshold: float = 0.05) -> int:
        """Phase 17B: Xóa mem yếu bằng API query thay vì while-loop.
        Giữ lại CORE, SEMANTIC và FLASHBULB.
        """
        results = self.collection.get(
            where={"strength": {"$lt": threshold}},
            include=["metadatas"]
        )
        if not results or not results.get('ids'):
            return 0
            
        ids_to_drop = []
        for i, meta in enumerate(results['metadatas']):
            if meta.get("is_flashbulb", 0) == 1: continue
            if meta.get("type") in ["core", "semantic"]: continue
            ids_to_drop.append(results['ids'][i])
            
        if ids_to_drop:
            self.collection.delete(ids=ids_to_drop)
            return len(ids_to_drop)
        return 0

    def clear_all(self):
        logger.warning("clear_all() called! Dropping aura_long_term_memory collection.")
        try:
            self.client.delete_collection(name="aura_long_term_memory")
            self.collection = self.client.get_or_create_collection(
                name="aura_long_term_memory",
                metadata={"hnsw:space": "cosine"}
            )
        except Exception:
            logger.error("Failed to clear_all", exc_info=True)

    def reset_collection(self):
        """Xóa vĩnh viễn collection hiện tại để tạo lại với kích thước vector mới (đổi model)"""
        print(f"{Fore.RED}⚠️ [VECTOR STORE]: Đang xóa toàn bộ bộ nhớ cũ để đồng bộ kích thước vector mới...{Style.RESET_ALL}")
        logger.warning("reset_collection() called! Destroying memory schema.")
        try:
            self.client.delete_collection(name="aura_long_term_memory")
        except Exception:
            pass
        self.collection = self.client.get_or_create_collection(
            name="aura_long_term_memory",
            metadata={"hnsw:space": "cosine"}
        )

    # ─────────────────────────────────────────────────
    # READ OPERATIONS
    # ─────────────────────────────────────────────────

    def get_all_metadata(self, limit: int = None, offset: int = None,
                         min_strength: float = None) -> List[Any]:
        """Lấy metadata có hỗ trợ phân trang (Pagination) và pre-filter bằng DB query.
        
        Phase 13: min_strength filter được áp dụng ở tầng DB (dùng lifted metadata)
        thay vì load hết rồi filter trong Python.
        """
        kwargs = {}
        if limit is not None:
            kwargs["limit"] = limit
        if offset is not None:
            kwargs["offset"] = offset

        # Phase 13: Pre-filter ở DB level bằng lifted 'strength' field
        if min_strength is not None:
            kwargs["where"] = {"strength": {"$gte": min_strength}}

        try:
            results = self.collection.get(**kwargs)
            if not results or not results.get('metadatas'):
                return []
            
            objs = []
            for meta_dict in results['metadatas']:
                obj = self._dict_to_obj(meta_dict)
                if obj is not None:
                    objs.append(obj)
            return objs
        except Exception:
            logger.error("Failed to get_all_metadata", exc_info=True)
            return []

    def get_by_time_range(self, start_time: float, end_time: float, limit: int = 10) -> List[Any]:
        """Truy xuất các vector theo dòng thời gian (chronological recall)"""
        results = self.collection.get(
            where={"$and": [
                {"timestamp": {"$gte": float(start_time)}},
                {"timestamp": {"$lte": float(end_time)}}
            ]},
            limit=limit
        )
        if not results or not results['metadatas']:
            return []
            
        objs = []
        for meta_dict in results['metadatas']:
            obj = self._dict_to_obj(meta_dict)
            if obj is not None:
                objs.append(obj)
             
        objs.sort(key=lambda x: getattr(x, 'created_at', 0.0), reverse=True)
        return objs

    def search(self, query_vec: np.ndarray, top_k: int = 5,
               min_strength: float = None) -> List[Tuple[float, Any]]:
        """Tìm kiếm vector tương đồng.
        
        Phase 13: Có thể pre-filter bằng 'strength' lifted field trước khi tìm vector,
        tránh kéo ký ức yếu ớt không liên quan vào kết quả.
        """
        count = self.collection.count()
        if count == 0:
            return []

        vec_to_query = query_vec.tolist() if hasattr(query_vec, 'tolist') else query_vec
        query_kwargs = {
            "query_embeddings": [vec_to_query],
            "n_results": min(top_k, count),
            "include": ["metadatas", "distances"]
        }

        # Phase 13: Pre-filter tại DB thay vì post-filter tại Python
        if min_strength is not None:
            query_kwargs["where"] = {"strength": {"$gte": min_strength}}
            
        results = self.collection.query(**query_kwargs)
        
        if not results['ids'] or len(results['ids'][0]) == 0:
            return []

        formatted_results = []
        for i in range(len(results['ids'][0])):
            distance = results['distances'][0][i]
            similarity = max(0.0, min(1.0, 1.0 - distance))
            meta_obj = self._dict_to_obj(results['metadatas'][0][i])
            if meta_obj is not None:
                formatted_results.append((similarity, meta_obj))

        return formatted_results
