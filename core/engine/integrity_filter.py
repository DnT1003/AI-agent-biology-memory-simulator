import re

from core.memory import MemoryType

# Phủ định khớp theo ranh giới từ (Python `re` mặc định Unicode nên \b đúng với
# chữ có dấu): "sai" không khớp "Sài Gòn", "not" không khớp "nothing".
_NEGATION_RE = re.compile(
    r"\b(không|chẳng|chả|chưa|đâu có|trái ngược|sai|"
    r"not|never|no|wrong|isn't|aren't|don't|doesn't)\b"
)
# Hỏi có/không tiếng Việt kết thúc bằng tiểu từ: "...có khỏe không?", "...ăn chưa?"
_TRAILING_QUESTION_PARTICLE_RE = re.compile(r"\b(không|chưa|chăng|hả|à|nhỉ)\s*\?*\s*$")


def _is_question(text: str) -> bool:
    stripped = text.strip()
    return stripped.endswith("?") or bool(_TRAILING_QUESTION_PARTICLE_RE.search(stripped))


def _has_negation(text: str) -> bool:
    lowered = text.lower()
    # "...không?" ở cuối câu hỏi là tiểu từ nghi vấn, không phải phủ định.
    lowered = _TRAILING_QUESTION_PARTICLE_RE.sub("", lowered.strip())
    return bool(_NEGATION_RE.search(lowered))


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
        # Một câu hỏi không khẳng định điều gì nên không thể mâu thuẫn logic.
        is_question = _is_question(new_content)
        new_negated = _has_negation(new_content)

        for b in beliefs:
            # 2. Kiểm tra mâu thuẫn Valence (Emotional Friction)
            # Nếu b là một niềm tin tích cực mà thông tin mới cực kỳ tiêu cực về cùng một đối tượng
            if abs(b.valence - new_valence) > 1.2:
                 conflict_detected = True
                 conflict_reason = f"Mâu thuẫn cảm xúc nặng nề với niềm tin: '{b.content[:50]}...'"
                 break

            # 3. Logic Contradiction (Simple Keyword reversal)
            # Ví dụ: "X là tốt" vs "X là xấu"
            if not is_question and _has_negation(b.content) != new_negated:
                 # Nếu một cái có phủ định, cái kia không -> Có khả năng mâu thuẫn
                 conflict_detected = True
                 conflict_reason = f"Mâu thuẫn logic tiềm tàng với niềm tin: '{b.content[:50]}...'"
                 break

        return {
            "conflict": conflict_detected,
            "reason": conflict_reason,
            "impact_multiplier": 1.5 if conflict_detected else 1.0
        }
