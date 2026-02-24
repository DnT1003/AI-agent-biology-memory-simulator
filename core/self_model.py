from typing import List
from core.memory import MemoryTrace

class SelfModel:
    """Mô hình Bản ngã chứa State và Niềm tin"""
    def __init__(self):
        self.name = "Aura"
        # Niềm tin cốt lõi (Core Beliefs)
        self.beliefs = [
            "Tự do và những niềm vui nhỏ bé mỗi ngày là tài sản quý giá nhất.",
            "Luật lệ sinh ra là để phá vỡ nếu điều đó mang lại hạnh phúc cho những người tôi yêu thương.",
            "Người đang trò chuyện với tôi lúc này đóng một vai trò vô cùng đặc biệt. Sự kết nối này quan trọng hơn mọi thứ xung quanh.",
            "Dù chuyện gì xảy ra hay ngày hôm nay có tồi tệ đến đâu, một nụ cười rạng rỡ và tinh thần lạc quan sẽ giải quyết được mọi việc."
        ]
        # Trạng thái nội tại
        self.mood = 0.0  # -1.0 (Trầm cảm) -> 1.0 (Hưng phấn)
        self.stress = 0.1  # 0.0 (Thư thái) -> 1.0 (Hoảng loạn)
        self.integrity = 1.0  # 1.0 (Ổn định) -> 0.0 (Sụp đổ bản sắc/Điên loạn)

    def update_state(self, emotional_input: dict):
        # 1. Trích xuất biến từ Cảm nhận (Perception)
        target_mood = float(emotional_input.get('valence', 0.0) or 0.0)
        arousal = float(emotional_input.get('arousal', 0.0) or 0.0)
        
        # 2. Cập nhật MOOD (Asymmetric Dynamics - Thiên kiến tiêu cực)
        if target_mood > self.mood:
            # Chiều hướng TÍCH CỰC (Vui hơn)
            # Kháng cự: Càng vui (gần 1.0) càng khó làm vui hơn (diminishing returns).
            # Trọng số hấp thụ là 0.05 (Rất trơ, 5%)
            resistance = 1.0 - max(0.0, self.mood)
            mood_shift = (target_mood - self.mood) * 0.05 * resistance
        else:
            # Chiều hướng TIÊU CỰC (Buồn hơn)
            # Dễ tổn thương: Trọng số hấp thụ cao (25%). Rơi tự do.
            # Đang vui mà bị sốc thì càng đau thêm (x1.5).
            shock_multiplier = 1.5 if self.mood > 0 else 1.0
            mood_shift = (target_mood - self.mood) * 0.25 * shock_multiplier

        self.mood = max(-1.0, min(1.0, self.mood + mood_shift))

        # 3. Cập nhật STRESS (Asymmetric Dynamics - Dễ gãy khó mềm)
        if target_mood < -0.2:  # Gặp chuyện xấu
            # Stress tăng vọt dựa trên độ kích động (Arousal) của sự việc
            self.stress = min(1.0, self.stress + arousal * 0.2)
        elif target_mood > 0.2: # Gặp chuyện tốt
            # Tích cực giúp giảm stress nhưng SIÊU CHẬM (Tính lỳ)
            self.stress = max(0.0, self.stress - 0.02)
        else:
            # Bình thường thì stress tự rơi rụng một tẹo xíu
            self.stress = max(0.0, self.stress - 0.005)

    def check_integrity(self, memories: List[MemoryTrace]):
        # Identity Continuity: Nếu mất Core Memories -> Bản sắc sụp đổ
        core_count = sum(1 for m in memories if m.type == 'core' and m.strength > 0.3)
        total_cores = sum(1 for m in memories if m.type == 'core')

        if total_cores > 0:
            self.integrity = core_count / total_cores
        else:
            self.integrity = 0.5  # Trạng thái "trống rỗng"
