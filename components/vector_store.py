import os
import chromadb
import json
from chromadb.config import Settings
import numpy as np
from typing import List, Tuple, Any

class VectorStore:
    """Kho lưu trữ vector nội bộ sử dụng ChromaDB cho khả năng Scale lớn và Persistence"""
    def __init__(self):
        # Đảm bảo thư mục tồn tại
        if not os.path.exists("outputs/chroma_db"):
            os.makedirs("outputs/chroma_db")
            
        # Khởi tạo Chroma Client lưu trữ Persistent trên ổ cứng
        self.client = chromadb.PersistentClient(path="outputs/chroma_db")
        
        # Tạo hoặc lấy Collection (Bảng dữ liệu) mang tên "aura_long_term_memory"
        # Khoảng cách cosine similarity (cosine) được bật mặc định
        self.collection = self.client.get_or_create_collection(
            name="aura_long_term_memory",
            metadata={"hnsw:space": "cosine"}
        )

    def _obj_to_dict(self, obj: Any) -> dict:
        """Helper chuyển Object sang chuỗi JSON để lưu vào metadata của Chroma"""
        return {
            "data": json.dumps(obj.__dict__, ensure_ascii=False),
            # Thêm timestamp độc lập để có thể filter bằng vòng lặp ChromaDB where
            "timestamp": float(getattr(obj, 'created_at', 0.0))
        }

    def _dict_to_obj(self, metadata_dict: dict) -> Any:
        """Helper phục hồi lại Object từ JSON"""
        # Lazy import để tránh Circular Dependency với MemoryManager
        from core.memory import MemoryTrace
        data = json.loads(metadata_dict["data"])
        return MemoryTrace(**data)

    def add(self, record_id: str, vector: np.ndarray, meta: Any):
        # Chroma yêu cầu nhét vector dưới dạng list python
        self.collection.add(
            ids=[record_id],
            embeddings=[vector.tolist()],
            metadatas=[self._obj_to_dict(meta)]
        )

    def update_meta(self, record_id: str, meta: Any):
        self.collection.update(
            ids=[record_id],
            metadatas=[self._obj_to_dict(meta)]
        )

    def update_vector(self, record_id: str, vector: np.ndarray):
        self.collection.update(
            ids=[record_id],
            embeddings=[vector.tolist()]
        )

    def remove(self, record_id: str):
        self.collection.delete(ids=[record_id])

    def clear_all(self):
        # Xóa theo collection có sẵn
        try:
            self.client.delete_collection(name="aura_long_term_memory")
            self.collection = self.client.get_or_create_collection(
                name="aura_long_term_memory",
                metadata={"hnsw:space": "cosine"}
            )
        except Exception:
            pass

    def get_all_metadata(self) -> List[Any]:
        results = self.collection.get()
        if not results or not results['metadatas']:
            return []
        
        objs = []
        for meta_dict in results['metadatas']:
             objs.append(self._dict_to_obj(meta_dict))
        return objs

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
             objs.append(self._dict_to_obj(meta_dict))
             
        # Sắp xếp lại theo thời gian giảm dần (mới nhất trước)
        objs.sort(key=lambda x: getattr(x, 'created_at', 0.0), reverse=True)
        return objs

    def search(self, query_vec: np.ndarray, top_k: int = 5) -> List[Tuple[float, Any]]:
        count = self.collection.count()
        if count == 0:
            return []
            
        # Truy vấn vào Chroma. Chroma sẽ trả về cosine distance.
        # Lưu ý: distance = 1 - similarity. Score cao = distance thấp.
        results = self.collection.query(
            query_embeddings=[query_vec.tolist()],
            n_results=min(top_k, count),
            include=["metadatas", "distances"]
        )
        
        if not results['ids'] or len(results['ids'][0]) == 0:
            return []

        formatted_results = []
        for i in range(len(results['ids'][0])):
            distance = results['distances'][0][i]
            # Chroma dùng cosine distance: sim = 1.0 - distance
            similarity = 1.0 - distance 
            meta_obj = self._dict_to_obj(results['metadatas'][0][i])
            formatted_results.append((similarity, meta_obj))

        # Đã được Chroma sort sẵn theo distance từ nhỏ đến lớn (sim từ cao xuống thấp)
        return formatted_results
