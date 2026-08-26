from core.memory import MemoryType

class IntegrityFilter:
    """
    Hệ thống 1: Kiểm tra mâu thuẫn nhận thức (Cognitive Dissonance).
    So khớp niềm tin mới với hệ thống niềm tin cũ bằng Semantic + Logic.
    """
    def __init__(self, engine):
        self.engine = engine

    def check_contradiction(self, new_content: str, new_valence: float) -> dict:
        """
        Kiểm tra xem thông tin mới có mâu thuẫn với niềm tin (Beliefs) hiện có không.
        """
        # 1. Tìm các niềm tin liên quan từ bộ nhớ CORE/SEMANTIC
        res = self.engine.memory.search_memories(f"Belief: {new_content}", top_k=3)
        beliefs = [m for score, m in res if m.type in [MemoryType.CORE, MemoryType.SEMANTIC] and score > 0.6]
        
        conflict_detected = False
        conflict_reason = ""
        
        for b in beliefs:
            # 2. Kiểm tra mâu thuẫn Valence (Emotional Friction)
            # Nếu b là một niềm tin tích cực mà thông tin mới cực kỳ tiêu cực về cùng một đối tượng
            if abs(b.valence - new_valence) > 1.2:
                 conflict_detected = True
                 conflict_reason = f"Mâu thuẫn cảm xúc nặng nề với niềm tin: '{b.content[:50]}...'"
                 break
            
            # 3. Logic Contradiction (Simple Keyword reversal)
            # Ví dụ: "X là tốt" vs "X là xấu"
            negations = ["không", "not", "never", "trái ngược", "sai", "wrong"]
            if any(n in b.content.lower() for n in negations) != any(n in new_content.lower() for n in negations):
                 # Nếu một cái có phủ định, cái kia không -> Có khả năng mâu thuẫn
                 conflict_detected = True
                 conflict_reason = f"Mâu thuẫn logic tiềm tàng với niềm tin: '{b.content[:50]}...'"
                 break

        return {
            "conflict": conflict_detected,
            "reason": conflict_reason,
            "impact_multiplier": 1.5 if conflict_detected else 1.0
        }
