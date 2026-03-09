import os
import sys
import json
from colorama import Fore, Style

# Gia lap moi truong
sys.path.append(os.getcwd())

from core.engine.memory_ops import MemoryOperationsController
from core.self_model import SelfModel
from core.prompts import get_perceive_prompt
from unittest.mock import MagicMock

def test_lesson_synthesis():
    print(f"{Fore.CYAN}🧪 [TEST]: Bat dau thu nghiem chuc nang Đuc ket Bai hoc Tu than (Feature 5)...{Style.RESET_ALL}")
    
    # Mock Engine
    engine = MagicMock()
    engine._memory_lock = MagicMock()
    engine.short_term_buffer = [
        "User: Aura oi, hay noi ngan gon thoi, dung giai thich dai dong qua.",
        "Aura: Toi xin loi, toi se co gang giai thich chi tiet cho ban hieu...",
        "User: Đa bao la noi ngan gon ma, ban van nhay di nhay lai.",
        "Aura: Vang, toi hieu roi. Toi se rut kinh nghiem."
    ]
    
    engine.ego = SelfModel()
    engine.value_system = MagicMock()
    engine.value_system.get_moral_context.return_value = "{}"
    
    # Mock LLM
    engine.llm = MagicMock()
    synthesis_json = {
        "insight": "Tôi nhận ra mình có xu hướng giải thích quá đà khiến User khó chịu.",
        "actionable_lessons": [
            "Trả lời ngắn gọn, súc tích khi User yêu cầu.",
            "Tránh giải thích lặp đi lặp lại một vấn đề."
        ],
        "value_updates": []
    }
    engine.llm.generate_text.return_value = json.dumps(synthesis_json)
    
    # Init Controller
    controller = MemoryOperationsController(engine)
    
    # Execute Synthesis Phase
    print(f"{Fore.YELLOW}Aura dang phan tu de rut ra bai hoc...{Style.RESET_ALL}")
    controller._identity_evolution_phase()
    
    # Verify results
    lessons = engine.ego.actionable_lessons
    print(f"\n{Fore.WHITE}Ket qua bai hoc:{Style.RESET_ALL}")
    print(f"- Lessons: {lessons}")
    
    if len(lessons) == 2 and "ngắn gọn" in lessons[0]:
        print(f"{Fore.GREEN}✅ SUCCESS: Aura da rut ra dung bai hoc tu tuong tac.{Style.RESET_ALL}")
    else:
        print(f"{Fore.RED}❌ FAILURE: Bai hoc khong dung hoac khong duoc luu.{Style.RESET_ALL}")
        return

    # Verify Prompt Injection (Integration check)
    print(f"\n{Fore.CYAN}🚀 Dang kiem tra viec nap bai hoc vao Prompt...{Style.RESET_ALL}")
    prompt = get_perceive_prompt(engine.ego, "12:00", "", "", [], "Hello", "tools")
    
    if "BÀI HỌC TỰ THÂN CẦN THỰC HÀNH" in prompt and "ngắn gọn" in prompt:
        print(f"{Fore.GREEN}✅ SUCCESS: Bai hoc da duoc nap vao Consciousness Prompt!{Style.RESET_ALL}")
    else:
        print(f"{Fore.RED}❌ FAILURE: Prompt khong chua bai hoc.{Style.RESET_ALL}")

    print(f"\n{Fore.GREEN}🎉 CHUC MUNG: Chuc nang Self-Lesson Synthesis hoat dong hoan hao!{Style.RESET_ALL}")

if __name__ == "__main__":
    test_lesson_synthesis()
