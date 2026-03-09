import os
import sys
import time
import json
from colorama import Fore, Style

# Gia lap moi truong de chay test
sys.path.append(os.getcwd())

from core.engine.cognitive_engine import CognitiveEngine
from config import Config

def test_autonomous_skill_creation():
    print(f"{Fore.CYAN}🧪 [TEST]: Bat dau thu nghiem chuc nang Tu tong hop Ky nang (Feature 4)...{Style.RESET_ALL}")
    
    # Mock Engine and Components to avoid Pydantic/Chroma errors
    from unittest.mock import MagicMock
    from core.engine.memory_ops import MemoryOperationsController
    
    engine = MagicMock()
    engine._memory_lock = MagicMock()
    engine.skills = MagicMock()
    engine.skills.get_prompt_instructions.return_value = "HỆ THỐNG CÔNG CỤ: Hiện tại chưa có công cụ BMI."
    engine.short_term_buffer = []
    
    # Mock LLM and Embedder
    engine.llm = MagicMock()
    engine.embedder = MagicMock()
    
    # Configure tool detection gap JSON
    gap_json = {
        "has_gap": True,
        "tool_name": "bmi_calculator",
        "description": "Tinh chi so khoi co the (BMI) dua tren can nang (kg) va chieu cao (m).",
        "required_logic": "bmi = weight / (height * height)"
    }
    engine.llm.generate_text.side_effect = [
        json.dumps(gap_json), # First call: gap detection
        """
def bmi_calculator(args):
    \"\"\"Tinh BMI. Tham so: 'kg m'\"\"\"
    try:
        w, h = map(float, args.split())
        bmi = w / (h * h)
        return f"BMI của bạn là {bmi:.2f}"
    except:
        return "Vui lòng nhập định dạng: 'cân_nặng chiều_cao' (VD: 70 1.75)"

DESCRIPTION = "Tính chỉ số BMI từ cân nặng và chiều cao."
USAGE = "ACTION: bmi_calculator | <cân_nặng> <chiều_cao>"
        """ # Second call: code synthesis
    ]
    
    # Initialize controller with mocked engine
    controller = MemoryOperationsController(engine)
    
    # 1. Gia lap tinh huong
    user_input = "Aura oi, hay tao mot cong cu de tinh chi so BMI cho toi nhe. Cong thuc la can nang / (chieu cao * chieu cao)."
    print(f"\n{Fore.WHITE}USER: {user_input}{Style.RESET_ALL}")
    
    # Force push vao short term buffer
    engine.short_term_buffer.append(f"User: {user_input}")
    
    print(f"\n{Fore.YELLOW}Aura dang ghi nhan thieu sot va vao xuong Tool Workshop...{Style.RESET_ALL}")
    
    # 2. Kick hoat Tool Workshop truc tiep
    controller._tool_workshop_phase()
    
    # Aura tiep nhan va luu vao short term memory
    perception = {
        "internal_monologue": "Nguoi dung muon minh tinh BMI. Minh chua co tool nay, minh can ghi nho de tu hoc khi ngu.",
        "valence": 0.1,
        "arousal": 0.5,
        "importance": 0.8,
        "type": "episodic"
    }
    engine.memory_ops.update_or_add_memory(user_input, perception)
    
    # Force push vao short term buffer (vi trong code that no duoc cap nhat qua interaction)
    with engine._memory_lock:
        engine.short_term_buffer.append(f"User: {user_input}")
    
    print(f"\n{Fore.YELLOW}Aura dang ghi nhan thieu sot va chuan bi di ngu...{Style.RESET_ALL}")
    
    # 2. Kick hoat pha Sleep (bao gom Tool Workshop)
    engine.memory_ops.sleep()
    
    # 3. Kiem tra xem file tool moi da duoc tao chua
    dynamic_dir = os.path.join("core", "dynamic_skills")
    generated_files = [f for f in os.listdir(dynamic_dir) if f.endswith(".py") and f != "__init__.py"]
    
    if generated_files:
        print(f"\n{Fore.GREEN}✅ SUCCESS: Aura da tu viet {len(generated_files)} tool moi: {generated_files}{Style.RESET_ALL}")
        
        # 4. Kiem tra xem tool da duoc nap vao Registry chua
        engine.skills.load_dynamic_skills()
        if "bmi_calculator" in engine.skills.skills or any("bmi" in name for name in engine.skills.skills):
            tool_name = [name for name in engine.skills.skills if "bmi" in name][0]
            print(f"{Fore.GREEN}✅ SUCCESS: Tool '{tool_name}' da duoc nap vao Registry!{Style.RESET_ALL}")
            
            # 5. Thu nghiem thuc thi tool moi
            print(f"\n{Fore.CYAN}🚀 Dang thu nghiem dung tool vua hoc duoc...{Style.RESET_ALL}")
            # Gia lap doi tham so: nang 70kg, cao 1.75m
            test_args = "70 1.75"
            result = engine.skills.execute(tool_name, test_args)
            print(f"{Fore.YELLOW}KET QUA TU TOOL MOI: {result}{Style.RESET_ALL}")
        else:
            print(f"{Fore.RED}❌ FAILURE: Tool khong tim thay trong Registry.{Style.RESET_ALL}")
    else:
        print(f"{Fore.RED}❌ FAILURE: Aura khong tao ra file tool nao.{Style.RESET_ALL}")

if __name__ == "__main__":
    # Clear old dynamic skills if any for clean test
    dynamic_dir = os.path.join("core", "dynamic_skills")
    for f in os.listdir(dynamic_dir):
        if f.endswith(".py") and f != "__init__.py":
            os.remove(os.path.join(dynamic_dir, f))
            
    test_autonomous_skill_creation()
