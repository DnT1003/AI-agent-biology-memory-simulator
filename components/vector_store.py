import numpy as np
from typing import List, Dict, Tuple, Any

class VectorStore:
    """Kho lưu trữ vector nội bộ mô phỏng hệ thống vector DB như mem0"""
    def __init__(self):
        self.vectors: Dict[str, np.ndarray] = {}  # id -> vector
        self.metadata: Dict[str, Any] = {}        # id -> meta obj

    def add(self, record_id: str, vector: np.ndarray, meta: Any):
        self.vectors[record_id] = vector
        self.metadata[record_id] = meta

    def clear_all(self):
        self.vectors.clear()
        self.metadata.clear()

    def remove(self, record_id: str):
        if record_id in self.vectors:
            del self.vectors[record_id]
        if record_id in self.metadata:
            del self.metadata[record_id]

    def update_meta(self, record_id: str, meta: Any):
        if record_id in self.metadata:
            self.metadata[record_id] = meta

    def update_vector(self, record_id: str, vector: np.ndarray):
        if record_id in self.vectors:
            self.vectors[record_id] = vector

    def get_all_metadata(self) -> List[Any]:
        return list(self.metadata.values())

    def search(self, query_vec: np.ndarray, top_k: int = 5) -> List[Tuple[float, Any]]:
        if not self.vectors:
            return []

        ids = list(self.vectors.keys())
        matrix = np.array([self.vectors[i] for i in ids])
        
        norms_matrix = np.linalg.norm(matrix, axis=1)
        norm_query = np.linalg.norm(query_vec)
        
        # Chống chia 0
        norms_matrix[norms_matrix == 0] = 1e-9
        if norm_query == 0:
            norm_query = 1e-9

        similarities = np.dot(matrix, query_vec) / (norms_matrix * norm_query)

        results = []
        for idx, sim in enumerate(similarities):
            results.append((sim, self.metadata[ids[idx]]))

        results.sort(key=lambda x: x[0], reverse=True)
        return results[:top_k]
