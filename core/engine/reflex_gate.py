import math
import random

class ReflexGate:
    """
    Hệ thống 1: Cổng phản xạ vô điều kiện/có điều kiện.
    Kích hoạt hành động tự động dựa trên áp lực sinh học mà không cần LLM.
    """
    SLEEP_REFLEX_MIN_FATIGUE = 0.75

    def __init__(self, engine):
        self.engine = engine

    def _sigmoid(self, x, k=10, threshold=0.5):
        """Hàm sigmoid để tính xác suất."""
        return 1 / (1 + math.exp(-k * (x - threshold)))

    def evaluate_reflexes(self) -> dict:
        """
        Kiểm tra xem Aura có nên tự động thực hiện hành động nào không.
        Trả về { "triggered": bool, "action": str, "reason": str }
        """
        ego = self.engine.ego
        
        # 1. Phản xạ Đi ngủ (Sleep Reflex): chỉ khi thật sự mệt, không phải
        # một xác suất nhỏ mỗi tin nhắn ở mọi mức mệt.
        # Đo theo ngưỡng gục ngã của hôm nay, để phản xạ "chào rồi đi ngủ" luôn
        # đến TRƯỚC lúc gục hẳn (interaction: fatigue >= fatigue_critical).
        critical = min(1.0, max(0.1, float(getattr(ego, "fatigue_critical", 1.0))))
        relative = ego.fatigue / critical
        if relative < self.SLEEP_REFLEX_MIN_FATIGUE:
            return {"triggered": False}
        p_sleep = self._sigmoid(relative, k=15, threshold=0.9)
        if random.random() < p_sleep:
             return {
                 "triggered": True, 
                 "action": "sleep", 
                 "reason": f"Kiệt sức tột độ (Fatigue: {ego.fatigue:.2f}), cơ thể tự ngắt kết nối."
             }
        
        # Tò mò được xử lý theo nhịp thời gian bởi AutonomousPacer (đọc sách),
        # không phải phản xạ mỗi tin nhắn.

        # 3. Phản xạ Giao tiếp (Social / Intimacy Reflex)
        # Nếu quá cô đơn, Aura có thể chủ động hỏi thăm sâu hơn (tương lai)

        return {"triggered": False}
