import os
import json
import time
try:
    import spacy
    SPACY_AVAILABLE = True
except Exception:
    SPACY_AVAILABLE = False
from typing import Dict, List, Set
from colorama import Fore, Style
from core.logger import get_logger

logger = get_logger("world_graph")

class WorldGraph:
    """Đồ thị Thế giới: Ghi nhớ các mối quan hệ xã hội của User và môi trường."""
    def __init__(self, filepath="outputs/world_graph.json"):
        self.filepath = filepath
        # data: dict { "EntityA": { "Relation": "EntityB", ... } }
        self.nodes = {} 
        self.edges = [] 
        
        # Load model NER Transformers (Phase 11)
        if SPACY_AVAILABLE:
            try:
                self.nlp = spacy.load("en_core_web_trf")
                logger.info("WorldGraph: Loaded en_core_web_trf successfully.")
            except Exception as e:
                logger.error(f"WorldGraph: Failed to load spaCy model: {e}")
                self.nlp = None
        else:
            logger.warning("WorldGraph: spaCy NOT AVAILABLE (Probably Pydantic v1 incompatibility on Python 3.14). Entity extraction disabled.")
            self.nlp = None

        self.load()

    def extract_entities(self, text: str) -> List[Dict]:
        """Sử dụng spaCy NER để tìm các thực thể quan trọng."""
        if not self.nlp: return []
        doc = self.nlp(text)
        entities = []
        for ent in doc.ents:
            # Chỉ lấy các thực thể liên quan đến xã hội/thực thể
            if ent.label_ in ["PERSON", "ORG", "GPE", "FAC", "PRODUCT"]:
                entities.append({
                    "text": ent.text,
                    "label": ent.label_
                })
        return entities

    def update_from_text(self, text: str, llm):
        """
        Sử dụng LLM (Ưu tiên Local) để trích xuất các quan hệ xã hội phức tạp và thái độ.
        Phù hợp với hướng tiến hóa: Social Reasoning.
        """
        # Phase 21 Optimization: Luôn ưu tiên Local LLM cho các tác vụ Extraction cấu trúc
        # để tiết kiệm API và đảm bảo tính riêng tư dữ liệu xã hội.
        use_local = True 
        
        prompt = f"""
        Phân tích câu nói sau để trích xuất các thực thể (Tên người, tổ chức) và MỐI QUAN HỆ giữa chúng.
        Câu nói: "{text}"
        
        Yêu cầu trích xuất theo định dạng JSON array:
        [
            {{
                "source": "Thực thể A (vd: User)", 
                "relation": "mối quan hệ ngắn gọn", 
                "target": "Thực thể B",
                "valence": <float từ -1.0 (ghét/tiêu cực) đến 1.0 (yêu/tích cực)>
            }}
        ]
        - Nếu User nhắc về bản thân (xưng tôi, tớ, mình...), hãy dùng "User" làm source.
        - Tên riêng phải viết hoa chữ cái đầu.
        - Nếu không có thông tin quan hệ xã hội, trả về [].
        """
        
        try:
            # Ép dùng local nếu có thể (thông qua params giả định hoặc logic trong components/llm.py)
            res = llm.generate_json(prompt, temperature=0.1, force_local=True)
            items = res if isinstance(res, list) else ([res] if isinstance(res, dict) else [])
            for item in items:
                self.add_relation(
                    item.get('source'),
                    item.get('relation'),
                    item.get('target'),
                    valence=item.get('valence', 0.0)
                )
        except Exception as e:
            logger.error(f"WorldGraph update error: {e}")

    def add_relation(self, source: str, relation: str, target: str, valence: float = 0.0):
        """Thêm quan hệ vào đồ thị kèm theo trọng số cảm xúc (Valence)."""
        if not source or not target or not relation: return False
        
        source, target = source.strip(), target.strip()
        
        # Cập nhật hoặc thêm mới
        for edge in self.edges:
            if edge['source'] == source and edge['target'] == target and edge['relation'] == relation:
                # Cập nhật valence mới nhất (có tính tích lũy nhẹ)
                edge['valence'] = edge.get('valence', 0.0) * 0.7 + valence * 0.3
                return True
                
        self.edges.append({
            "source": source,
            "relation": relation,
            "target": target,
            "valence": valence,
            "timestamp": time.time()
        })
        
        if source not in self.nodes: self.nodes[source] = {"type": "Entity"}
        if target not in self.nodes: self.nodes[target] = {"type": "Entity"}
            
        print(f"{Fore.CYAN}🌐 [WORLD GRAPH]: {source} --({relation}, val:{valence:+.1f})--> {target}{Style.RESET_ALL}")
        self.save()
        return True

    def query(self, entity_name: str) -> List[str]:
        """Truy xuất thông tin liên quan đến một Entity kèm theo Valence."""
        results = []
        entity_name = entity_name.strip()
        for edge in self.edges:
            if entity_name in edge['source'] or entity_name in edge['target']:
                v = edge.get('valence', 0.0)
                v_str = f" [valence:{v:+.1f}]" if v != 0 else ""
                results.append(f"{edge['source']} {edge['relation']} {edge['target']}{v_str}")
        return results

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.filepath) or ".", exist_ok=True)
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump({"nodes": self.nodes, "edges": self.edges}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Lỗi lưu WorldGraph: {e}")

    def load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.nodes = data.get("nodes", {})
                    self.edges = data.get("edges", [])
            except Exception as e:
                logger.error(f"Lỗi đọc WorldGraph: {e}")
