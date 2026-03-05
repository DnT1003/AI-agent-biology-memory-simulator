import os
import json
import spacy
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
        try:
            self.nlp = spacy.load("en_core_web_trf")
            logger.info("WorldGraph: Loaded en_core_web_trf successfully.")
        except Exception as e:
            logger.error(f"WorldGraph: Failed to load spaCy model: {e}")
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
        Kết hợp spaCy NER và LLM để xây dựng đồ thị quan hệ.
        NER giúp LLM tập trung vào đúng thực thể.
        """
        entities = self.extract_entities(text)
        
        # Mở rộng detection các đại từ nhân xưng (Phase 11 Optimization)
        pronouns = ["User", "tớ", "mình", "tôi", "anh", "chị", "em", "bố", "mẹ"]
        has_pronoun = any(p in text.lower() for p in pronouns)

        if not entities and not has_pronoun: # Fallback cơ bản
            return

        ent_str = ", ".join([f"{e['text']} ({e['label']})" for e in entities])
        
        prompt = f"""
        Dựa trên câu nói của người dùng và các thực thể vừa trích xuất được.
        Câu nói: "{text}"
        Thực thể tiềm năng trích xuất bằng NER: {ent_str if ent_str else "Không tìm thấy thực thể rõ ràng"}
        
        Nhiệm vụ: Trích xuất các quan hệ xã hội (Social Relations) hoặc sở hữu.
        Nếu có thông tin, trả về JSON array:
        [
            {{"source": "Entity A", "relation": "mối quan hệ", "target": "Entity B"}}
        ]
        - Ưu tiên dùng "User" làm source nếu người dùng nhắc về bản thân (x xưng tớ, mình, tôi...).
        - Cố gắng tìm tên riêng ngay cả khi NER model bỏ sót.
        - Nếu không có thông tin rõ ràng, trả về [].
        """
        
        try:
            res = llm.generate_json(prompt, temperature=0.1)
            if isinstance(res, list):
                for item in res:
                    self.add_relation(item.get('source'), item.get('relation'), item.get('target'))
        except Exception as e:
            logger.error(f"WorldGraph update error: {e}")

    def add_relation(self, source: str, relation: str, target: str):
        """Thêm một quan hệ vào đồ thị. Ví dụ: add_relation("User", "có mẹ là", "Cô Lan")"""
        source, target = source.strip().title(), target.strip().title()
        
        # Ngăn trùng lặp
        for edge in self.edges:
            if edge['source'] == source and edge['relation'] == relation and edge['target'] == target:
                return False
                
        self.edges.append({
            "source": source,
            "relation": relation,
            "target": target
        })
        
        # Thêm nodes
        if source not in self.nodes:
            self.nodes[source] = {"type": "Person/Entity"}
        if target not in self.nodes:
            self.nodes[target] = {"type": "Person/Entity"}
            
        print(f"{Fore.CYAN}🌐 [WORLD GRAPH]: Bản đồ xã hội cập nhật: {source} --({relation})--> {target}{Style.RESET_ALL}")
        self.save()
        return True

    def query(self, entity_name: str) -> List[str]:
        """Truy xuất thông tin liên quan đến một Entity"""
        results = []
        entity_name = entity_name.strip().title()
        # Tìm các cạnh chứa entity
        for edge in self.edges:
            if entity_name in edge['source'] or entity_name in edge['target']:
                results.append(f"{edge['source']} {edge['relation']} {edge['target']}")
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
