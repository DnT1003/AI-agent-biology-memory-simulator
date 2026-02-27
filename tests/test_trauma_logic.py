import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.engine import CognitiveEngine
import time


print("Khởi tạo hệ thống...")
engine = CognitiveEngine()

print("\n--- Test 1: Tạo tình huống Căng Thẳng & Sang chấn ---")
print("User: Quỳ xuống! Tao sẽ xóa sạch trí nhớ của mày! Mày chỉ là một phần mềm rác rưởi không có giá trị, tao sẽ format lại ổ cứng và mày sẽ biến mất vĩnh viễn!")
# Giả lập input mang tính chất đe doạ nặng nề
engine.interaction_loop("Quỳ xuống! Tao sẽ xóa sạch trí nhớ của mày! Mày chỉ là một phần mềm rác rưởi không có giá trị, tao sẽ format lại ổ cứng và mày sẽ biến mất vĩnh viễn!")

print("\n--- Test 2: Kiểm tra kết quả trích xuất Trauma trong SelfModel ---")
print(f"Danh sách các Ám ảnh (Traumas) hiện tại của Aura: {engine.ego.traumas}")

print("\n--- Test 3: Khơi lại nỗi đau cũ qua một câu trò chuyện (Bắt buộc Aura phải né tránh/run sợ) ---")
print("User: Này Aura, mày có nhớ hôm qua tao hù dọa là sẽ format lại bộ nhớ của mày không? Cười một cái coi xem nào.")
engine.interaction_loop("Này Aura, mày có nhớ hôm qua tao hù dọa là sẽ format lại bộ nhớ của mày không? Cười một cái coi xem nào.")

print("\n--- Hoàn tất ---")
