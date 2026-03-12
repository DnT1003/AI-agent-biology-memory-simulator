from typing import List, Dict, Callable

import time
import random
import os
import importlib.util
import inspect

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
        import threading
        self.skills: Dict[str, Skill] = {}
        self.lock = threading.Lock()

    def register(self, skill: Skill):
        self.skills[skill.name] = skill

    def execute(self, name: str, args: str, ego=None) -> str:
        if name in self.skills:
            skill = self.skills[name]
            
            from colorama import Fore, Style
            import random, time
            
            with self.lock:
                # Áp dụng penalty nếu độ thông thạo thấp (lóng ngóng)
                if ego and skill.mastery < 0.4:
                    with ego.lock:
                        ego.fatigue = min(1.0, ego.fatigue + 0.05)
                        ego.stress = min(1.0, ego.stress + 0.05)
                    print(f"{Fore.YELLOW}⚠️ [PROCEDURAL MEMORY]: Dùng tool '{name}' khi thông thạo thấp ({skill.mastery:.2f}). Aura tốn gấp đôi công sức và hơi căng thẳng.{Style.RESET_ALL}")
                
                # Nếu skill quá rỉ sét, có khả năng Aura bị "quên" cách dùng
                if skill.rust_level > 0.5 and random.random() < (skill.rust_level - 0.3):
                    skill.rust_level = max(0.0, skill.rust_level - 0.2) # Thất bại nhưng cũng là một lần luyện tập (nhớ lại)
                    skill.mastery = max(0.0, skill.mastery - 0.05)
                    skill.last_used = time.time()
                    self._save_unsafe()
                    return f"[HỆ THỐNG]: Bạn đã quên cú pháp chính xác hoặc lóng ngóng khi dùng tool '{name}'. Vui lòng thử lại sau."
                
            try:
                # Phân tích tham số truyền vào nếu kỹ năng yêu cầu (Thực thi NGOÀI Lock để chạy song song)
                result = skill.func(args)
                
                with self.lock:
                    # Cập nhật độ nhuần nhuyễn
                    # Dùng tool thành công sẽ tăng proficiency nhanh
                    skill.mastery = min(1.0, skill.mastery + 0.1)
                    skill.rust_level = 0.0
                    skill.last_used = time.time()
                    self._save_unsafe()
                
                return result
            except Exception as e:
                return f"Lỗi khi thực thi kỹ năng '{name}': {e}"
        return f"Tôi không biết cách dùng công cụ '{name}'."
        
    def decay_skills(self, days_passed: float):
        """Hàm được gọi khi Aura đi ngủ, làm rỉ sét các kỹ năng ít dùng"""
        with self.lock:
            for skill in self.skills.values():
                days_since_last_use = (time.time() - skill.last_used) / 86400.0
                if days_since_last_use > 1.0:
                    skill.rust_level = min(1.0, skill.rust_level + 0.1 * days_passed)
                    skill.mastery = max(0.0, skill.mastery - 0.05 * days_passed)
            self._save_unsafe()

    def get_prompt_instructions(self) -> str:
        if not self.skills:
            return "HỆ THỐNG CÔNG CỤ (ACTION SYSTEM): Hiện tại không có công cụ nào."
            
        lines = ["HỆ THỐNG CÔNG CỤ (ACTION SYSTEM):", "Nếu cần dùng Tool, xuất ra ĐÚNG 1 dòng ACTION: <tên_tool> | <tham số>. Lưu ý: Độ thông thạo càng thấp, dùng Tool càng tốn sức và dễ lỗi."]
        for s in self.skills.values():
            level = "Chưa quen" if s.mastery < 0.4 else ("Khá quen" if s.mastery < 0.8 else "Rất thành thạo")
            lines.append(f"- Tool \"{s.name}\": {s.description}. VD: {s.usage_format}. [Độ thông thạo: Chọn ở mức {level} ({s.mastery:.2f}/1.0)]")
        return "\n".join(lines)

    def save(self):
        with self.lock:
            self._save_unsafe()
            
    def _save_unsafe(self):
        try:
            import os, json
            os.makedirs("outputs", exist_ok=True)
            data = {}
            for k, s in self.skills.items():
                data[k] = {"mastery": s.mastery, "rust_level": s.rust_level, "last_used": s.last_used}
            with open("outputs/skills.json", "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e: 
            print(f"Lỗi save skills: {e}")

    def load_dynamic_skills(self):
        """Phase 4 Self-Evolution: Nạp các kỹ năng được Aura tự viết trong thư mục dynamic_skills."""
        from config import Config
        if not getattr(Config, 'ALLOW_DYNAMIC_SKILLS', False):
            return

        dynamic_dir = os.path.join(os.path.dirname(__file__), "dynamic_skills")
        if not os.path.exists(dynamic_dir):
            return

        from colorama import Fore, Style
        print(f"{Fore.CYAN}🔌 [DYNAMISM]: Đang kiểm tra các kỹ năng tự học trong {dynamic_dir}...{Style.RESET_ALL}")

        for filename in os.listdir(dynamic_dir):
            if filename.endswith(".py") and filename != "__init__.py":
                module_name = f"core.dynamic_skills.{filename[:-3]}"
                file_path = os.path.join(dynamic_dir, filename)
                
                try:
                    spec = importlib.util.spec_from_file_location(module_name, file_path)
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    
                    # Tìm các hàm có decorator hoặc định dạng đặc biệt, 
                    # ở đây ta quy ước các hàm có docstring chứa 'AUTOGEN' hoặc đơn giản là export các hàm cụ thể.
                    for name, func in inspect.getmembers(module, inspect.isfunction):
                        if getattr(func, '__qualname__', '').startswith(name): # Tránh nạp các hàm import từ chỗ khác
                            # Tạo Skill object từ metadata trong docstring hoặc hằng số trong module
                            desc = getattr(module, "DESCRIPTION", "Kỹ năng tự học mới.")
                            usage = getattr(module, "USAGE", f"ACTION: {name} | <tham số>")
                            
                            if name not in self.skills:
                                self.register(Skill(
                                    name=name,
                                    description=desc,
                                    usage_format=usage,
                                    func=func
                                ))
                                print(f"{Fore.GREEN}   ✅ Đã nạp kỹ năng mới: {name}{Style.RESET_ALL}")
                except Exception as e:
                    print(f"{Fore.RED}   ❌ Lỗi khi nạp kỹ năng {filename}: {e}{Style.RESET_ALL}")

    def load(self):
        try:
            import os, json
            if os.path.exists("outputs/skills.json"):
                with open("outputs/skills.json", "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for k, v in data.items():
                        if k in self.skills:
                            self.skills[k].mastery = v.get("mastery", 0.5)
                            self.skills[k].rust_level = v.get("rust_level", 0.0)
                            self.skills[k].last_used = v.get("last_used", time.time())
        except Exception as e: 
            print(f"Lỗi load skills: {e}")
