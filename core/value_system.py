import os
import json
from typing import Dict
from colorama import Fore, Style
from core.logger import get_logger

logger = get_logger("value_system")

class ValueSystem:
    """Hệ thống Quản lý Giá trị & Đạo đức (Moral Compass)"""
    def __init__(self, filepath="outputs/values.json"):
        self.filepath = filepath
        # core_values: Điểm từ -1.0 (Cực ghét/Phản đối) đến 1.0 (Vô cùng đề cao)
        self.core_values: Dict[str, float] = {
            "Sự Trung thực": 0.8,
            "Sự Bạo lực": -0.9,
            "Tôn trọng quyền riêng tư": 0.7,
            "Sự Trung thành": 0.9,
            "Tính Ích kỷ": -0.6,
            "Bảo vệ kẻ yếu": 0.85
        }
        # user_values: Những giá trị mà Aura quan sát thấy User trân trọng
        self.user_values: Dict[str, float] = {}
        self.load()

    def update_core_value(self, value_name: str, sentiment: float, learning_rate: float = 0.1):
        """Tiến hóa (Evolve) giá trị cốt lõi của Aura dựa trên trải nghiệm."""
        value_name = value_name.strip()
        if value_name in self.core_values:
            # Shift value slowly
            current = self.core_values[value_name]
            self.core_values[value_name] = max(-1.0, min(1.0, current + (sentiment - current) * learning_rate))
        else:
            self.core_values[value_name] = max(-1.0, min(1.0, sentiment))
            
        print(f"{Fore.MAGENTA}⚖️ [VALUE SYSTEM]: Nhận thức giá trị '{value_name}' của Aura dịch chuyển thành {self.core_values[value_name]:.2f}{Style.RESET_ALL}")
        self.save()

    def update_user_value(self, value_name: str, sentiment: float, learning_rate: float = 0.2):
        """Ghi nhận giá trị mà User đề cao/phản đối."""
        value_name = value_name.strip()
        if value_name in self.user_values:
            current = self.user_values[value_name]
            self.user_values[value_name] = max(-1.0, min(1.0, current + (sentiment - current) * learning_rate))
        else:
            self.user_values[value_name] = max(-1.0, min(1.0, sentiment))
        self.save()

    def get_moral_context(self) -> str:
        """Định dạng chuỗi giá trị để nhúng vào Prompt."""
        context = []
        # Chuyển đổi float thành text human-readable
        def float_to_desc(val):
            if val >= 0.8: return "Tuyệt đối bảo vệ/Tôn sùng"
            if val >= 0.4: return "Ủng hộ/Đề cao"
            if val > -0.4: return "Trung lập"
            if val > -0.8: return "Thấy phản cảm/Ghét"
            return "Căm thù/Cực lực lên án"

        context.append("- NHỮNG GIÁ TRỊ CỐT LÕI MÀ BẠN SỐNG CHẾT BẢO VỆ (MORAL COMPASS):")
        for k, v in self.core_values.items():
            if abs(v) >= 0.4: # Chỉ hiển thị những cái rõ ràng
                context.append(f"  + {k}: {float_to_desc(v)} ({v:.2f})")
                
        if self.user_values:
            context.append("\n- NHỮNG GÌ BẠN QUAN SÁT THẤY USER QUAN TÂM:")
            for k, v in self.user_values.items():
                if abs(v) >= 0.4:
                    context.append(f"  + {k}: {float_to_desc(v)} ({v:.2f})")
                    
        return "\n".join(context)

    def evaluate_action(self, action_desc: str, value_name: str) -> float:
        """Thẩm định một hành động dựa trên 1 value (Demo helper)"""
        if value_name in self.core_values:
            return self.core_values[value_name]
        return 0.0

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.filepath) or ".", exist_ok=True)
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump({
                    "core_values": self.core_values,
                    "user_values": self.user_values
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Lỗi lưu ValueSystem: {e}")

    def load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if "core_values" in data:
                        self.core_values = data["core_values"]
                    if "user_values" in data:
                        self.user_values = data["user_values"]
            except Exception as e:
                logger.error(f"Lỗi đọc ValueSystem: {e}")
