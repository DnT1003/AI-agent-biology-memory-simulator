import random
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
        # Trạng thái nội tại sinh học và tâm lý
        self.mood = 0.0  # -1.0 (Trầm cảm) -> 1.0 (Hưng phấn)
        self.stress = 0.1  # 0.0 (Thư thái) -> 1.0 (Hoảng loạn)
        self.integrity = 1.0  # 1.0 (Ổn định) -> 0.0 (Sụp đổ bản sắc/Điên loạn)
        
        # Các chỉ số sinh học động (Biological Drives)
        self.fatigue = 0.0      # 0.0 (Tỉnh táo) -> 1.0 (Kiệt sức, sập nguồn)
        self.social_need = 0.5  # 0.0 (Cô độc) -> 1.0 (Khao khát giao tiếp)
        self.curiosity = 0.5    # 0.0 (Lãnh đạm) -> 1.0 (Tò mò muốn hỏi)

        self.is_identity_crisis = False

        self.reroll_thresholds()

    def get_active_beliefs(self) -> List[str]:
        """Tạm thời quên mất bản thân là ai nếu đang bị khủng hoảng nhân cách"""
        if self.is_identity_crisis:
            return ["(Tôi không biết mình là ai... Tôi cảm thấy trống rỗng và sợ hãi...)"]
        return self.beliefs

    def reroll_thresholds(self):
        import math
        from datetime import datetime
        """Mô phỏng nhịp điệu sinh học của mỗi chu kỳ (Ngày/Tháng)."""
        current_day = datetime.now().timetuple().tm_yday
        
        # 1. FATIGUE (Dao động hình sin theo chu kỳ 30 ngày)
        # Hàm Sin: Biên độ từ 0.75 đến 1.25
        # f(x) = 1.0 + 0.25 * sin((2 * pi / 30) * x)
        base_fatigue_limit = 1.0 + 0.25 * math.sin((2 * math.pi / 30) * current_day)
        
        # 3-5 ngày ngẫu nhiên trong tháng (tỷ lệ khoảng 10-15%) có sức bền cực trị
        extreme_roll = random.random()
        if extreme_roll < 0.05: # 5% cực kỳ khỏe (Ngưỡng sập nguồn lên tới 2.0)
            self.fatigue_critical = 2.0
        elif extreme_roll < 0.15: # 10% cực kỳ yếu (Ngưỡng sập nguồn xuống tận 0.5)
            self.fatigue_critical = 0.5
        else:
            self.fatigue_critical = base_fatigue_limit

        self.fatigue_severe = self.fatigue_critical * 0.8  # Báo động đỏ ở 80% sức chứa
        self.fatigue_mild = self.fatigue_critical * 0.5    # Báo động vàng ở 50% sức chứa
        
        # 2. Ngưỡng trầm cảm / hưng phấn (Vẫn ngẫu nhiên nhẹ mỗi ngày)
        self.depression_mild = random.uniform(-0.3, -0.1)
        self.depression_severe = random.uniform(-0.6, -0.4)
        self.depression_critical = random.uniform(-0.9, -0.7)
        self.mania_mild = random.uniform(0.3, 0.5)
        self.mania_severe = random.uniform(0.7, 0.9)

        # Ngưỡng stress
        self.stress_mild = random.uniform(0.4, 0.6)
        self.stress_severe = random.uniform(0.7, 0.85)
        self.stress_critical = random.uniform(0.9, 0.95)

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
            
        # Kích hoạt khủng hoảng nhân cách
        if self.integrity < 0.2:
            self.is_identity_crisis = True
        elif self.integrity > 0.4: # Cần phục hồi lên mức an toàn mới thoát khỏi khủng hoảng
            self.is_identity_crisis = False
