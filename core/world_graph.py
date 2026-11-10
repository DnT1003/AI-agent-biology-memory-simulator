import os
import json
import time
import copy
import math
import re
import threading
from numbers import Real
from typing import Dict, List, Set
from colorama import Fore, Style
from core.logger import get_logger
from core.utils import atomic_write_json

logger = get_logger("world_graph")

class WorldGraph:
    """Đồ thị Thế giới: Ghi nhớ các mối quan hệ xã hội của User và môi trường."""

    _MAX_TEXT_LENGTH = 256
    _MAX_RELATIONS_PER_UPDATE = 64
    _MAX_NODES = 10_000
    _MAX_EDGES = 50_000
    _MAX_STATE_BYTES = 10 * 1024 * 1024

    def __init__(self, filepath="outputs/world_graph.json"):
        self.filepath = filepath
        self.lock = threading.Lock()
        # data: dict { "EntityA": { "Relation": "EntityB", ... } }
        self.nodes = {} 
        self.edges = [] 
        # Entities are extracted by the LLM (update_from_text); the former
        # English spaCy NER model was never called and is not loaded.

        self.load()

    @classmethod
    def _validated_text(cls, value, field: str) -> str:
        if not isinstance(value, str):
            raise ValueError(f"{field} must be a string")
        value = value.strip()
        if not value or len(value) > cls._MAX_TEXT_LENGTH:
            raise ValueError(f"{field} has invalid length")
        if any(ord(character) < 32 for character in value):
            raise ValueError(f"{field} contains control characters")
        return value

    @staticmethod
    def _validated_valence(value) -> float:
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError("valence must be numeric")
        value = float(value)
        if not math.isfinite(value) or not -1.0 <= value <= 1.0:
            raise ValueError("valence must be finite and within [-1, 1]")
        return value

    @classmethod
    def _validate_relation(cls, item) -> tuple[str, str, str, float]:
        if not isinstance(item, dict):
            raise ValueError("relation must be an object")
        source = cls._validated_text(item.get("source"), "source")
        relation = cls._validated_text(item.get("relation"), "relation")
        target = cls._validated_text(item.get("target"), "target")
        valence = cls._validated_valence(item.get("valence", 0.0))
        return source, relation, target, valence

    @classmethod
    def _validate_extraction(cls, payload) -> list[tuple[str, str, str, float]]:
        if not isinstance(payload, dict):
            raise ValueError("world graph extraction must be an object")
        if "relations" in payload:
            items = payload["relations"]
            if not isinstance(items, list):
                raise ValueError("relations must be a list")
        elif {"source", "relation", "target"}.issubset(payload):
            # Compatibility with the former single-relation response shape.
            items = [payload]
        else:
            raise ValueError("world graph extraction is missing relations")
        if len(items) > cls._MAX_RELATIONS_PER_UPDATE:
            raise ValueError("too many relations")
        # Validate every item before any in-memory or durable mutation.
        return [cls._validate_relation(item) for item in items]

    @classmethod
    def _validate_state(cls, payload) -> tuple[dict, list]:
        if not isinstance(payload, dict):
            raise ValueError("world graph state must be an object")
        nodes = payload.get("nodes", {})
        edges = payload.get("edges", [])
        if not isinstance(nodes, dict) or len(nodes) > cls._MAX_NODES:
            raise ValueError("invalid world graph nodes")
        if not isinstance(edges, list) or len(edges) > cls._MAX_EDGES:
            raise ValueError("invalid world graph edges")

        validated_nodes = {}
        for name, metadata in nodes.items():
            name = cls._validated_text(name, "node name")
            if name in validated_nodes:
                raise ValueError("duplicate node name")
            if not isinstance(metadata, dict):
                raise ValueError("node metadata must be an object")
            node_type = metadata.get("type", "Entity")
            node_type = cls._validated_text(node_type, "node type")
            validated_nodes[name] = {"type": node_type}

        validated_edges = []
        edge_keys = set()
        for item in edges:
            source, relation, target, valence = cls._validate_relation(item)
            if source not in validated_nodes or target not in validated_nodes:
                raise ValueError("edge endpoint is missing from nodes")
            edge_key = (source, relation, target)
            if edge_key in edge_keys:
                raise ValueError("duplicate world graph edge")
            edge_keys.add(edge_key)
            timestamp = item.get("timestamp", 0.0)
            if isinstance(timestamp, bool) or not isinstance(timestamp, Real):
                raise ValueError("timestamp must be numeric")
            timestamp = float(timestamp)
            if not math.isfinite(timestamp) or timestamp < 0.0:
                raise ValueError("timestamp must be finite and non-negative")
            validated_edges.append({
                "source": source,
                "relation": relation,
                "target": target,
                "valence": valence,
                "timestamp": timestamp,
            })
        return validated_nodes, validated_edges

    @staticmethod
    def _log_failure(operation: str, exc: BaseException) -> None:
        try:
            logger.error(
                "WorldGraph %s failed cause_type=%s",
                operation,
                type(exc).__name__,
            )
        except Exception:
            # Diagnostics must never change the operation's failure contract.
            pass

    def update_from_text(
        self,
        text: str,
        llm,
        model_override: str | None = None,
        *,
        force_local: bool = False,
    ):
        """
        Sử dụng LLM để trích xuất các quan hệ xã hội phức tạp và thái độ.
        """
        
        prompt = f"""
        Phân tích câu nói sau để trích xuất các thực thể (Tên người, tổ chức) và MỐI QUAN HỆ giữa chúng.
        Câu nói: "{text}"
        
        Yêu cầu trích xuất theo định dạng JSON object:
        {{
          "relations": [
            {{
                "source": "Thực thể A (vd: User)", 
                "relation": "mối quan hệ ngắn gọn", 
                "target": "Thực thể B",
                "valence": <float từ -1.0 (ghét/tiêu cực) đến 1.0 (yêu/tích cực)>
            }}
          ]
        }}
        - Nếu User nhắc về bản thân (xưng tôi, tớ, mình...), hãy dùng "User" làm source.
        - Tên riêng phải viết hoa chữ cái đầu.
        - Nếu không có thông tin quan hệ xã hội, trả về {{"relations": []}}.
        """
        
        try:
            res, _ = llm.generate_json(
                prompt,
                temperature=0.1,
                model_override=model_override,
                force_local=force_local,
                bio_throttle=False,
            )
        except Exception as exc:
            self._log_failure("extraction", exc)
            return False
        return self.apply_extraction(res)

    def apply_extraction(self, payload) -> bool:
        """Validate and commit an already-extracted {"relations": [...]} payload."""
        try:
            relations = self._validate_extraction(payload)
        except Exception as exc:
            self._log_failure("extraction", exc)
            return False

        if not relations:
            return True

        with self.lock:
            nodes_snapshot = copy.deepcopy(self.nodes)
            edges_snapshot = copy.deepcopy(self.edges)
            try:
                for source, relation, target, valence in relations:
                    self._add_relation_unsafe(source, relation, target, valence)
                self._save_unsafe()
            except BaseException as exc:
                self.nodes.clear()
                self.nodes.update(nodes_snapshot)
                self.edges[:] = edges_snapshot
                if isinstance(exc, Exception):
                    self._log_failure("commit", exc)
                    return False
                raise

        for source, relation, target, valence in relations:
            print(
                f"{Fore.CYAN}🌐 [WORLD GRAPH]: {source} "
                f"--({relation}, val:{valence:+.1f})--> {target}{Style.RESET_ALL}"
            )
        return True

    def add_relation(self, source: str, relation: str, target: str, valence: float = 0.0):
        """Thêm quan hệ vào đồ thị kèm theo trọng số cảm xúc (Valence)."""
        try:
            validated = self._validate_relation({
                "source": source,
                "relation": relation,
                "target": target,
                "valence": valence,
            })
        except Exception as exc:
            self._log_failure("validation", exc)
            return False

        with self.lock:
            nodes_snapshot = copy.deepcopy(self.nodes)
            edges_snapshot = copy.deepcopy(self.edges)
            try:
                self._add_relation_unsafe(*validated)
                self._save_unsafe()
            except BaseException as exc:
                self.nodes.clear()
                self.nodes.update(nodes_snapshot)
                self.edges[:] = edges_snapshot
                if isinstance(exc, Exception):
                    self._log_failure("commit", exc)
                    return False
                raise

        source, relation, target, valence = validated
        print(
            f"{Fore.CYAN}🌐 [WORLD GRAPH]: {source} "
            f"--({relation}, val:{valence:+.1f})--> {target}{Style.RESET_ALL}"
        )
        return True

    def _add_relation_unsafe(
        self,
        source: str,
        relation: str,
        target: str,
        valence: float,
    ) -> None:
        # Caller owns self.lock and has validated the full operation first.
        for edge in self.edges:
            if edge['source'] == source and edge['target'] == target and edge['relation'] == relation:
                current_valence = self._validated_valence(
                    edge.get('valence', 0.0)
                )
                edge['valence'] = current_valence * 0.7 + valence * 0.3
                return

        if len(self.edges) >= self._MAX_EDGES:
            raise ValueError("world graph edge limit reached")
        new_nodes = len({source, target}.difference(self.nodes))
        if len(self.nodes) + new_nodes > self._MAX_NODES:
            raise ValueError("world graph node limit reached")
                
        self.edges.append({
            "source": source,
            "relation": relation,
            "target": target,
            "valence": valence,
            "timestamp": time.time()
        })
        
        if source not in self.nodes: self.nodes[source] = {"type": "Entity"}
        if target not in self.nodes: self.nodes[target] = {"type": "Entity"}

    @staticmethod
    def _same_entity(a: str, b: str) -> bool:
        return a.casefold() == b.casefold()

    def relations_for(self, entity_name: str, limit: int | None = None) -> List[Dict]:
        """Edges whose source or target IS ``entity_name`` (case-insensitive).

        Strongest feelings first, then most recent, so a cap keeps what matters.
        """
        if not isinstance(entity_name, str) or not entity_name.strip():
            return []
        entity_name = entity_name.strip()
        with self.lock:
            edges = [
                copy.deepcopy(edge) for edge in self.edges
                if self._same_entity(edge['source'], entity_name)
                or self._same_entity(edge['target'], entity_name)
            ]
        edges.sort(
            key=lambda e: (abs(e.get('valence', 0.0)), e.get('timestamp', 0.0)),
            reverse=True,
        )
        return edges if limit is None else edges[:max(0, int(limit))]

    def query(self, entity_name: str, limit: int | None = None) -> List[str]:
        """Truy xuất thông tin liên quan đến một Entity kèm theo Valence.

        Khớp nguyên tên thực thể: "An" không còn khớp nhầm "Lan" hay "Toàn".
        """
        results = []
        for edge in self.relations_for(entity_name, limit):
            v = edge.get('valence', 0.0)
            v_str = f" [valence:{v:+.1f}]" if v != 0 else ""
            results.append(f"{edge['source']} {edge['relation']} {edge['target']}{v_str}")
        return results

    def find_mentions(self, text: str, limit: int = 5) -> List[str]:
        """Known entities mentioned as whole words in ``text``.

        Longer names win ("Nguyễn Văn An" before "An") and a name contained in
        an already-matched longer mention is not reported again.
        """
        if not isinstance(text, str) or not text.strip():
            return []
        lowered = text.casefold()
        with self.lock:
            names = [n for n in self.nodes if n != "User" and len(n) >= 2]
        names.sort(key=len, reverse=True)
        found, spans = [], []
        for name in names:
            pattern = r"(?<!\w)" + re.escape(name.casefold()) + r"(?!\w)"
            match = re.search(pattern, lowered)
            if match is None:
                continue
            if any(start <= match.start() and match.end() <= end for start, end in spans):
                continue
            spans.append(match.span())
            found.append(name)
            if len(found) >= limit:
                break
        return found

    def _save_unsafe(self) -> None:
        nodes, edges = self._validate_state({
            "nodes": self.nodes,
            "edges": self.edges,
        })
        payload = {"nodes": nodes, "edges": edges}
        # The writer must never emit a file that this class will reject on the
        # next start. Count limits alone are insufficient because names and
        # relations are variable-length UTF-8 strings.
        encoded_size = len(json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8"))
        if encoded_size > self._MAX_STATE_BYTES:
            raise ValueError("world graph state is too large")
        atomic_write_json(
            self.filepath,
            payload,
        )

    def save(self):
        with self.lock:
            try:
                self._save_unsafe()
                return True
            except Exception as exc:
                self._log_failure("save", exc)
                return False

    def load(self):
        if not os.path.exists(self.filepath):
            return False
        try:
            with self.lock:
                if os.path.getsize(self.filepath) > self._MAX_STATE_BYTES:
                    raise ValueError("world graph state is too large")
                with open(self.filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                nodes, edges = self._validate_state(data)
                self.nodes.clear()
                self.nodes.update(nodes)
                self.edges[:] = edges
            return True
        except Exception as exc:
            self._log_failure("load", exc)
            return False
