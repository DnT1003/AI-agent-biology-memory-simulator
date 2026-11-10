import math
import re

# Từ khóa song ngữ (Việt + Anh). Python `re` mặc định Unicode nên \b hoạt
# động đúng với chữ có dấu.
_DOMINANCE_RE = re.compile(
    r'\b(do|must|tell|give|search|start|stop'
    r'|hãy|phải|làm đi|nói đi|đưa|tìm|bắt đầu|dừng|cấm|ra lệnh)\b'
)
_LOW_CERTAINTY_RE = re.compile(
    r'\b(maybe|perhaps|i think|probably|not sure'
    r'|có lẽ|chắc là|hình như|không chắc|có khi|tôi nghĩ|mình nghĩ)\b'
)
_HIGH_CERTAINTY_RE = re.compile(
    r'\b(sure|defined|always|never|fact'
    r'|chắc chắn|luôn luôn|không bao giờ|sự thật|rõ ràng)\b'
)
_URGENCY_RE = re.compile(
    r'\b(fast|now|immediately|quick|hurry|urgent'
    r'|nhanh lên|ngay|lập tức|gấp|khẩn cấp|mau lên)\b'
)


def _valid_valence(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    value = float(value)
    if not math.isfinite(value):
        return 0.0
    return max(-1.0, min(1.0, value))


class SensoryPreprocessor:
    """
    Hệ thống 0 (Phản xạ tiền nhận thức):
    Phân tích thuộc tính vật lý và cảm xúc thô của Input trước khi chuyển cho LLM.

    Valence không được tính ở đây: nó đến từ LocalPerception (mô hình cảm xúc
    tiếng Việt chạy trong GPU service) qua `user_context["valence"]`. Không có
    giá trị đó thì valence trung tính (0.0).
    """

    def evaluate_input(self, text: str, user_context: dict | None = None) -> dict:
        # 1. Valence (Vui/Buồn) từ mô hình cảm xúc bên ngoài
        valence = _valid_valence((user_context or {}).get("valence", 0.0))

        # 2. Phân tích Arousal (Kích động) dựa trên cường độ văn bản
        # Logic: Dấu chấm than, viết hoa toàn bộ, và các từ nhấn mạnh tăng Arousal
        # isupper() nhận cả chữ hoa có dấu (Đ, Ứ, Ầ...), khác với [A-Z].
        upper_ratio = sum(1 for ch in text if ch.isupper()) / (len(text) + 1)
        exclamation_count = text.count('!')
        question_count = text.count('?')

        arousal = min(1.0, (abs(valence) * 0.5) + (upper_ratio * 0.5) + (exclamation_count * 0.1))

        lowered = text.lower()

        # 3. Phân tích Dominance (Quyền lực/Sự tự tin của User)
        # User ra lệnh (Dominance cao) vs User hỏi han (Dominance thấp)
        dominance = 0.5
        if _DOMINANCE_RE.search(lowered):
            dominance += 0.2
        if question_count > 0:
            dominance -= 0.1

        # 4. Certainty (Độ chắc chắn)
        certainty = 0.5
        if _LOW_CERTAINTY_RE.search(lowered):
            certainty -= 0.3
        elif _HIGH_CERTAINTY_RE.search(lowered):
            certainty += 0.3

        # 5. Urgency (Tính cấp bách)
        urgency = 0.0
        if _URGENCY_RE.search(lowered):
            urgency += 0.6
        urgency = min(1.0, urgency + (exclamation_count * 0.2))

        return {
            "vector": {
                "valence": round(valence, 3),
                "arousal": round(arousal, 3),
                "dominance": round(dominance, 3),
                "certainty": round(certainty, 3),
                "urgency": round(urgency, 3)
            },
            "summary": self._generate_sensory_summary(valence, arousal, urgency)
        }

    def _generate_sensory_summary(self, valence, arousal, urgency) -> str:
        tag = "Bình thường"
        if urgency > 0.7:
             tag = "CẤP BÁCH"
        if arousal > 0.8:
             tag = "KÍCH ĐỘNG"
        if valence < -0.6:
             tag = "TIÊU CỰC NẶNG"

        return f"[Hệ thống 0 - Phản xạ tiền nhận thức]: Tín hiệu {tag} ghi nhận. Valence: {valence}, Arousal: {arousal}."
