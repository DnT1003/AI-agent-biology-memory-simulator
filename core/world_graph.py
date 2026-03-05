import os
import json
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
        self.load()

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
