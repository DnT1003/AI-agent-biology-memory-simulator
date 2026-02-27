from typing import List, Dict, Callable

import time
import random

class Skill:
    def __init__(self, name: str, description: str, usage_format: str, func: Callable):
        self.name = name
        self.description = description
        self.usage_format = usage_format
        self.func = func
        self.mastery = 0.5      # Độ tinh thông: 0.0 -> 1.0
        self.rust_level = 0.0   # Sự mai một: 0.0 -> 1.0
        self.last_used = time.time()

class SkillRegistry:
    """Procedural Memory - Ký ức Thực hành (Sổ tay Kỹ năng)"""
    def __init__(self):
        self.skills: Dict[str, Skill] = {}

    def register(self, skill: Skill):
        self.skills[skill.name] = skill

    def execute(self, name: str, args: str) -> str:
        if name in self.skills:
            skill = self.skills[name]
            
            # Nếu skill quá rỉ sét, có khả năng Aura bị "quên" cách dùng
            if skill.rust_level > 0.5 and random.random() < (skill.rust_level - 0.3):
                skill.rust_level = max(0.0, skill.rust_level - 0.2) # Thất bại nhưng cũng là một lần luyện tập (nhớ lại)
                skill.mastery = max(0.0, skill.mastery - 0.05)
                skill.last_used = time.time()
                return f"[HỆ THỐNG]: Bạn đã quên cú pháp chính xác hoặc lóng ngóng khi dùng tool '{name}'. Vui lòng thử lại sau."
                
            try:
                # Phân tích tham số truyền vào nếu kỹ năng yêu cầu
                result = skill.func(args)
                
                # Cập nhật độ nhuần nhuyễn
                skill.mastery = min(1.0, skill.mastery + 0.1)
                skill.rust_level = 0.0
                skill.last_used = time.time()
                
                return result
            except Exception as e:
                return f"Lỗi khi thực thi kỹ năng '{name}': {e}"
        return f"Tôi không biết cách dùng công cụ '{name}'."
        
    def decay_skills(self, days_passed: float):
        """Hàm được gọi khi Aura đi ngủ, làm rỉ sét các kỹ năng ít dùng"""
        for skill in self.skills.values():
            days_since_last_use = (time.time() - skill.last_used) / 86400.0
            if days_since_last_use > 1.0:
                skill.rust_level = min(1.0, skill.rust_level + 0.1 * days_passed)
                skill.mastery = max(0.0, skill.mastery - 0.05 * days_passed)

    def get_prompt_instructions(self) -> str:
        if not self.skills:
            return "HỆ THỐNG CÔNG CỤ (ACTION SYSTEM): Hiện tại không có công cụ nào."
            
        lines = ["HỆ THỐNG CÔNG CỤ (ACTION SYSTEM):", "Nếu cần dùng Tool, xuất ra ĐÚNG 1 dòng ACTION: <tên_tool> | <tham số>"]
        for s in self.skills.values():
            lines.append(f"- Tool \"{s.name}\": {s.description}. VD: {s.usage_format}")
        return "\n".join(lines)
