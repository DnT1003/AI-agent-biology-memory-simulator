import math
import random

class ReflexGate:
    """
    Hệ thống 1: Cổng phản xạ vô điều kiện/có điều kiện.
    Kích hoạt hành động tự động dựa trên áp lực sinh học mà không cần LLM.
    """
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
        
        # 1. Phản xạ Đi ngủ (Sleep Reflex)
        p_sleep = self._sigmoid(ego.fatigue, threshold=0.9)
        if random.random() < p_sleep:
             return {
                 "triggered": True, 
                 "action": "sleep", 
                 "reason": f"Kiệt sức tột độ (Fatigue: {ego.fatigue:.2f}), cơ thể tự ngắt kết nối."
             }
        
        # 2. Phản xạ Tò mò (Curiosity / Search Reflex)
        # Nếu tò mò cực cao và không mệt, có xác suất tự đi tìm thông tin
        p_search = self._sigmoid(ego.curiosity, threshold=0.85) * (1.0 - ego.fatigue)
        if random.random() < p_search * 0.1: # Giới hạn tỷ lệ tự kích hoạt
             return {
                 "triggered": True,
                 "action": "search_novel|ngẫu nhiên",
                 "reason": "Sự tò mò thôi thúc tôi phải tìm kiếm điều gì đó mới mẻ."
             }
             
        # 3. Phản xạ Giao tiếp (Social / Intimacy Reflex)
        # Nếu quá cô đơn, Aura có thể chủ động hỏi thăm sâu hơn (tương lai)

        return {"triggered": False}
