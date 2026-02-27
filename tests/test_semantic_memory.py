import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.engine import CognitiveEngine

engine = CognitiveEngine()
print("\n--- Test 1: Khai báo Sự thật khách quan ---")
print("User: Bạn có biết rằng Trái Đất quay quanh Mặt Trời không?")
engine.interaction_loop("Bạn có biết rằng Trái Đất quay quanh Mặt Trời không?")

print("\n--- Test 2: Truy xuất lại sự thật vừa học ---")
print("User: Trái Đất quay quanh ai?")
engine.interaction_loop("Trái Đất quay quanh ai?")

print("\n--- Test 3: Test Tool (Skill Registry) ---")
print("User: Hiện tại đang là mấy giờ?")
engine.interaction_loop("Hiện tại đang là mấy giờ?")

print("\n--- Hoàn tất ---")
