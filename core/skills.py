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
        self.engine = None # Will be set by CognitiveEngine

    def _ego_action(self, arg, action_type):
        if not self.engine: return "Engine not connected."
        if action_type == "add_goal":
            self.engine.ego.add_goal(arg)
            return f"Mục tiêu '{arg}' đã được thiết lập."
        return "Unknown ego action."

    def _reader_action(self, arg, action_type):
        if not self.engine: return "Engine not connected."
        if action_type == "search_novel":
            import threading
            def _async():
                res = self.engine.reader.search_and_set_novel(arg)
                print(f"\n[READER]: {res}")
            threading.Thread(target=_async, daemon=True).start()
            return f"Đang tìm kiếm truyện '{arg}'..."
        return "Unknown reader action."

    def _autonomous_action(self, arg, action_type):
        if not self.engine: return "Engine not connected."
        if action_type == "start_reading":
            import threading
            threading.Thread(target=self.engine.autonomous.start_reading_task, args=("User request",), daemon=True).start()
            return "Bắt đầu đọc sách."
        return "Unknown autonomous action."

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

    def _save_unsafe(self):
        from core.utils import atomic_write_json
        from config import Config
        data = {k: {"mastery": s.mastery, "rust_level": s.rust_level, "last_used": s.last_used} for k, s in self.skills.items()}
        atomic_write_json(Config.SKILLS_FILE, data)

    def save(self):
        from core.utils import atomic_write_json
        from config import Config
        with self.lock:
            data = {k: {"mastery": s.mastery, "rust_level": s.rust_level, "last_used": s.last_used} for k, s in self.skills.items()}
            atomic_write_json(Config.SKILLS_FILE, data)

    def load_dynamic_skills(self):
        """Phase 4 Self-Evolution: Nạp các kỹ năng được Aura tự viết trong thư mục dynamic_skills, chạy qua Sandbox."""
        import os, ast, subprocess, json, sys
        from config import Config
        from colorama import Fore, Style
        
        if not getattr(Config, 'ALLOW_DYNAMIC_SKILLS', False):
            return

        dynamic_dir = os.path.join(os.path.dirname(__file__), "dynamic_skills")
        if not os.path.exists(dynamic_dir):
            return

        print(f"{Fore.CYAN}🔌 [DYNAMISM]: Đang kiểm tra an toàn và nạp kỹ năng tại {dynamic_dir}...{Style.RESET_ALL}")

        # §6.2 SECURITY FIX: Chuyển sang WHITELIST thay vì BLACKLIST.
        # Chỉ cho phép các module được kiểm duyệt rõ ràng.
        # Blacklist bị bypass bởi: urllib, pathlib, importlib.import_module("os")
        ALLOWED_IMPORTS = {
            'math', 'json', 're', 'datetime', 'collections',
            'itertools', 'functools', 'string', 'textwrap', 'random',
            'time', 'decimal', 'fractions', 'statistics', 'hashlib',
            'base64', 'uuid', 'copy', 'dataclasses', 'enum', 'typing',
        }
        # Các hàm/built-in luôn bị cấm dù module nào
        DANGEROUS_CALLS = {'exec', 'eval', 'open', '__import__', 'compile',
                           'globals', 'locals', 'vars', 'getattr', 'setattr', 'delattr'}

        def _is_safe_ast(source: str) -> tuple[bool, str]:
            """Kiểm tra AST với whitelist. Trả về (is_safe, reason)."""
            try:
                import ast as _ast
                tree = _ast.parse(source)
            except SyntaxError as e:
                return False, f"Lỗi cú pháp: {e}"

            for node in _ast.walk(tree):
                # Chặn mọi import không nằm trong whitelist
                if isinstance(node, _ast.Import):
                    for alias in node.names:
                        top = alias.name.split('.')[0]
                        if top not in ALLOWED_IMPORTS:
                            return False, f"Module '{alias.name}' không được phép (chỉ cho phép: {sorted(ALLOWED_IMPORTS)})"
                elif isinstance(node, _ast.ImportFrom):
                    top = (node.module or "").split('.')[0]
                    if top not in ALLOWED_IMPORTS:
                        return False, f"Import từ '{node.module}' không được phép"
                # Chặn importlib.import_module bypass
                elif isinstance(node, _ast.Call):
                    if isinstance(node.func, _ast.Name) and node.func.id in DANGEROUS_CALLS:
                        return False, f"Lời gọi nguy hiểm: '{node.func.id}'"
                    if isinstance(node.func, _ast.Attribute):
                        if node.func.attr in ('import_module', 'exec_module'):
                            return False, f"Lời gọi importlib bypass bị chặn: '{node.func.attr}'"
            return True, "OK"

        def create_sandbox_executor(f_path, f_name):
            def executor(args_str):
                snippet = f"""
import sys, json, os
sys.path.insert(0, os.path.dirname(r'{f_path}'))
import {os.path.basename(f_path)[:-3]} as mod
try:
    res = mod.{f_name}(sys.argv[1])
    print(json.dumps({{"result": res}}))
except Exception as e:
    print(json.dumps({{"error": str(e)}}))
"""
                try:
                    proc = subprocess.run(
                        [sys.executable, "-c", snippet, args_str],
                        capture_output=True, text=True, timeout=5.0
                    )
                    if proc.returncode != 0:
                        return f"[SANDBOX FATAL]: {proc.stderr.strip()}"
                    
                    return_lines = [l for l in proc.stdout.strip().split('\\n') if l]
                    if not return_lines:
                        return "[SANDBOX EMPTY]"
                    try:
                        data = json.loads(return_lines[-1])
                        if "error" in data: return f"[SKILL ERROR]: {data['error']}"
                        return data.get("result", str(return_lines[-1]))
                    except json.JSONDecodeError:
                        return f"[SKILL OUTPUT]: {proc.stdout.strip()}"
                except subprocess.TimeoutExpired:
                    return f"{Fore.RED}[SANDBOX BLOCKED]: Kỹ năng '{f_name}' chạy quá 5 giây (Nguy cơ Infinite Loop) và đã bị ngắt!{Style.RESET_ALL}"
                except Exception as e:
                    return f"[SANDBOX FAULT]: {e}"
            return executor

        for filename in os.listdir(dynamic_dir):
            if filename.endswith(".py") and filename != "__init__.py":
                file_path = os.path.join(dynamic_dir, filename)
                
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        source = f.read()
                    
                    # §6.2 SECURITY FIX: Dùng _is_safe_ast() (whitelist) thay vì AST blacklist cũ
                    is_safe, block_reason = _is_safe_ast(source)
                    if not is_safe:
                        print(f"{Fore.RED}   ❌ BLOCK: Kỹ năng {filename} bị từ chối — {block_reason}{Style.RESET_ALL}")
                        continue
                    
                    import ast
                    tree = ast.parse(source)
                        
                    desc = "Kỹ năng tự học hệ thống."
                    usage = "ACTION: func | <tham số>"
                    funcs = []

                    for node in tree.body:
                        if isinstance(node, ast.Assign):
                            for target in node.targets:
                                if isinstance(target, ast.Name):
                                    if target.id == 'DESCRIPTION' and isinstance(node.value, ast.Constant):
                                        desc = str(node.value.value)
                                    elif target.id == 'USAGE' and isinstance(node.value, ast.Constant):
                                        usage = str(node.value.value)
                        elif isinstance(node, ast.FunctionDef):
                            if not node.name.startswith('_'):
                                funcs.append(node.name)

                    for name in funcs:
                        if name not in self.skills:
                            self.register(Skill(
                                name=name,
                                description=desc,
                                usage_format=usage,
                                func=create_sandbox_executor(file_path, name)
                            ))
                            print(f"{Fore.GREEN}   🛡️ Đã nạp Sandbox an toàn cho kỹ năng: {name}{Style.RESET_ALL}")
                            
                except Exception as e:
                    print(f"{Fore.RED}   ❌ Lỗi khi phân tích Sandbox {filename}: {e}{Style.RESET_ALL}")

    def load(self):
        from core.utils import atomic_read_json
        from config import Config
        if not os.path.exists(Config.SKILLS_FILE):
            return
        try:
            with self.lock:
                data = atomic_read_json(Config.SKILLS_FILE)
                for k, v in data.items():
                    if k in self.skills:
                        self.skills[k].mastery = v.get("mastery", 0.5)
                        self.skills[k].rust_level = v.get("rust_level", 0.0)
                        self.skills[k].last_used = v.get("last_used", time.time())
        except Exception as e:
            print(f"Lỗi load skills: {e}")
