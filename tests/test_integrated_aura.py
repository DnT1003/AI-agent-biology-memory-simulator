"""
Test tích hợp: Mô phỏng CognitiveEngine xử lý input "đọc sách" và kiểm tra tính năng sinh lý.
"""
import time
import sys
import os
sys.path.insert(0, '.')
from colorama import Fore, Style

# Mocking or using real classes
try:
    from core.engine.cognitive_engine import CognitiveEngine
    print(f"{Fore.GREEN}✅ Import CognitiveEngine OK{Style.RESET_ALL}")
except Exception as e:
    print(f"{Fore.RED}❌ Import FAIL: {e}{Style.RESET_ALL}")
    sys.exit(1)

def run_test():
    print("\n" + "="*50)
    print("🚀 BẮT ĐẦU TEST TÍCH HỢP AURA")
    print("="*50)

    # 1. Khởi tạo Engine
    print("\n[1] Khởi tạo CognitiveEngine (Gồm SelfModel, Reader, etc.)...")
    engine = CognitiveEngine()
    
    # Ép trạng thái sinh lý để test mood_modifier
    engine.ego.fatigue = 0.9  # Rất mệt
    engine.ego.mood = -0.8    # Trầm cảm nặng
    print(f"   📊 Trạng thái SET: Fatigue={engine.ego.fatigue}, Mood={engine.ego.mood}")

    # 2. Test Instant Book Reading via Chat
    user_input = "Giới thiệu truyện: Tôi là quái vật"
    print(f"\n[2] User: '{user_input}'")
    print("    (Kiểm tra xem Aura có nhận diện được yêu cầu đọc sách không...)")
    
    # Chạy interaction_loop
    # Lưu ý: interaction_loop in trực tiếp ra console
    engine.interaction_loop(user_input)
    
    # 3. Kiểm tra Reader State
    print("\n[3] Kiểm tra trạng thái BackgroundReader...")
    if engine.reader.current_novel_title:
        print(f"   ✅ Aura đã nạp: '{engine.reader.current_novel_title}'")
        print(f"   📖 Hàng đợi chương: {len(engine.reader.chapters_queue)} chương")
    else:
        print("   ❌ Aura không tự động nạp truyện. Kiểm tra logic regex trong interaction.py!")

    # 4. Test Goal Engine (Nếu LLM output ACTION: add_goal)
    # Simulator: Ép 1 ACTION giả
    print("\n[4] Kiểm tra Goal Engine...")
    engine.ego.add_goal("Trở thành AI mạnh mẽ nhất")
    goals = engine.ego.get_active_goals()
    if goals:
        print(f"   ✅ Goals active: {goals}")
    else:
        print("   ❌ Không có goal nào.")

    # 5. Kiểm tra Circadian Rhythm
    print("\n[5] Kiểm tra Circadian Rhythm...")
    old_fatigue = engine.ego.fatigue
    engine.ego.apply_circadian_rhythm()
    print(f"   📊 Fatigue biến thiên: {old_fatigue:.2f} -> {engine.ego.fatigue:.2f}")

    print("\n" + "="*50)
    print("✨ TEST HOÀN TẤT")
    print("="*50)

if __name__ == "__main__":
    run_test()
