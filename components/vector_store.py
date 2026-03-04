import os
import chromadb
import json
from chromadb.config import Settings
import numpy as np
from typing import List, Tuple, Any, Dict, Optional

from colorama import Fore, Style
from core.logger import get_logger

logger = get_logger("vector_store")

# Các trường được "lift" ra top-level metadata (indexable, filterable)
LIFTED_FIELDS = {"type", "valence", "importance", "strength", "is_flashbulb"}


class VectorStore:
    """Kho lưu trữ vector nội bộ sử dụng ChromaDB cho khả năng Scale lớn và Persistence
    
    Phase 13: Metadata Lifting — các trường quan trọng (type, strength, valence, ...)
    được lưu thành top-level keys riêng trong ChromaDB metadata, cho phép filter ở tầng DB
    thay vì load hết về Python rồi mới lọc (không hiệu quả với 100k+ memories).
    """
    def __init__(self):
        if not os.path.exists("outputs/chroma_db"):
            os.makedirs("outputs/chroma_db")
            
        self.client = chromadb.PersistentClient(path="outputs/chroma_db")
        self.collection = self.client.get_or_create_collection(
            name="aura_long_term_memory",
            metadata={"hnsw:space": "cosine"}
        )

    # ─────────────────────────────────────────────────
    # INTERNAL SERIALIZATION / DESERIALIZATION
    # ─────────────────────────────────────────────────

    def _obj_to_dict(self, obj: Any) -> dict:
        """Chuyển Object sang ChromaDB metadata.
        
        Các trường trong LIFTED_FIELDS được lưu thành top-level key riêng để
        ChromaDB có thể filter mà không cần load JSON phụ.
        """
        raw = obj.__dict__.copy()
        meta = {
            "data": json.dumps(raw, ensure_ascii=False),
            "timestamp": float(getattr(obj, 'created_at', 0.0)),
            "schema_version": "3",  # Phase 13: schema version bump for metadata lifting
        }
        # Lift các trường quan trọng ra ngoài JSON để ChromaDB index
        for field in LIFTED_FIELDS:
            val = raw.get(field)
            if val is not None:
                if isinstance(val, bool):
                    meta[field] = int(val)  # ChromaDB không hỗ trợ bool trực tiếp
                elif isinstance(val, (int, float, str)):
                    meta[field] = val
                else:
                    meta[field] = str(val)  # enum → str
        return meta

    def _dict_to_obj(self, metadata_dict: dict) -> Any:
        """Phục hồi Object từ JSON. Safe fallback nếu schema cũ."""
        from core.memory import MemoryTrace
        try:
            data = json.loads(metadata_dict["data"])
            known_fields = {f.name for f in MemoryTrace.__dataclass_fields__.values()}
            data = {k: v for k, v in data.items() if k in known_fields}
            return MemoryTrace(**data)
        except Exception:
            logger.error("Failed to deserialize MemoryTrace", exc_info=True)
            return None

    # ─────────────────────────────────────────────────
    # WRITE OPERATIONS
    # ─────────────────────────────────────────────────

    def add(self, record_id: str, vector: np.ndarray, meta: Any):
        try:
            self.collection.upsert(
                ids=[record_id],
                embeddings=[vector.tolist()],
                metadatas=[self._obj_to_dict(meta)]
            )
        except Exception:
            logger.error(f"Failed to upsert vector {record_id}", exc_info=True)

    def add_batch(self, record_ids: List[str], vectors: List[np.ndarray], metas: List[Any]):
        """Batch upsert tối ưu cho tốc độ khi nạp data lớn."""
        try:
            self.collection.upsert(
                ids=record_ids,
                embeddings=[v.tolist() for v in vectors],
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

        query_kwargs = {
            "query_embeddings": [query_vec.tolist()],
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
