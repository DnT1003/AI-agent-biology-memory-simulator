import os
import time
from datetime import datetime
from colorama import Fore, Style
from config import Config

class PerceptionController:
    """
    [Phase 23] PerceptionController: Unifies all sensory inputs into a coherent context.
    Consolidates text sentiment, vision results, and environmental factors.
    """
    def __init__(self, engine):
        self.engine = engine

    def get_environmental_context(self) -> str:
        """Thu thập dữ liệu từ môi trường hệ thống và thời gian."""
        hour = datetime.now().hour
        time_desc = "Ban ngày"
        if 22 <= hour or hour < 5:
            time_desc = "Ban đêm (Khuya)"
        elif 18 <= hour < 22:
            time_desc = "Buổi tối"
        elif 5 <= hour < 11:
            time_desc = "Buổi sáng"

        # Giả lập Storage Pressure (đã có logic trong cognitive_tick, lấy lại từ Config)
        storage_info = ""
        try:
            if os.path.exists(Config.CHROMA_DB_PATH):
                # Đã được tính toán trong engine.cognitive_tick, ta chỉ cần mô tả trạng thái
                db_size_mb = self._get_dir_size(Config.CHROMA_DB_PATH) / (1024 * 1024)
                if db_size_mb > (Config.MAX_STORAGE_SIZE / (1024 * 1024)):
                    storage_info = f"\n[ÁP LỰC LƯU TRỮ]: Bộ nhớ đang quá tải ({db_size_mb:.1f}MB). Bạn cảm thấy 'nặng đầu' và Stress tăng cao."
        except Exception:
            pass

        return f"[MÔI TRƯỜNG]: {time_desc}. {storage_info}"

    def process_text_input(self, text: str) -> dict:
        """Phân tích cảm xúc từ text input của User."""
        if hasattr(self.engine, 'local_perception'):
            return self.engine.local_perception.analyze(text)
        return {"valence": 0.0, "arousal": 0.5, "importance": 0.5}

    def get_sensory_summary(self, user_input: str) -> str:
        """Tổng hợp toàn bộ context cảm giác thành một chuỗi prompt."""
        env = self.get_environmental_context()
        
        # Lấy kết quả từ Local Perception
        sentiment = self.process_text_input(user_input)
        valence = sentiment.get('valence', 0.0)
        arousal = sentiment.get('arousal', 0.5)
        
        sentiment_desc = "Bình thường"
        if valence > 0.4: sentiment_desc = "Tích cực/Vui vẻ"
        elif valence < -0.4: sentiment_desc = "Tiêu cực/Căng thẳng"
        
        if arousal > 0.7: sentiment_desc += " (Kích động)"
        
        # Biological state summary (Fatigue, Stress, Hunger)
        bio = f"[SINH LÝ]: Fatigue: {self.engine.ego.fatigue:.2f}, Stress: {self.engine.ego.stress:.2f}, Energy/Satiety: {self.engine.ego.energy:.2f}"
        
        summary = f"""
--- HỆ THỐNG CẢM GIÁC (SENSORY INPUT) ---
{env}
{bio}
[SẮC THÁI USER]: {sentiment_desc} (Valence: {valence:+.2f})
-----------------------------------------
"""
        return summary

    def _get_dir_size(self, path):
        total = 0
        try:
            with os.scandir(path) as it:
                for entry in it:
                    if entry.is_file(): total += entry.stat().size
                    elif entry.is_dir(): total += self._get_dir_size(entry.path)
        except Exception as e:
            from core.logger import get_logger
            get_logger("perception").warning(f"Lỗi phân tích cảm xúc cục bộ: {e}")
        return total
