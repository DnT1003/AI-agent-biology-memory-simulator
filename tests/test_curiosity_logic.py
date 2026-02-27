import sys
import codecs
sys.stdout = codecs.open('tests/curiosity_output.txt', 'w', encoding='utf-8')

import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.engine import CognitiveEngine
import time

print("Khởi tạo hệ thống...")
engine = CognitiveEngine()

print("\n--- Test 1: Ép Aura tự tạo mục tiêu thông qua Sự Tò Mò ---")
engine.ego.curiosity = 0.95 # Ép tò mò cực đại
engine.ego.beliefs = [
    "Tôi là một người cực kỳ đam mê thiên văn học, luôn thích ngắm sao hỏa.",
    "Tôi cho rằng người ngoài hành tinh chắc chắn có tồn tại."
] # Ép niềm tin giả để test độ bám sát tính cách

print(f"Niềm tin định hướng (Test): {engine.ego.beliefs}")

# Trigger self_generate_autonomous_goal trực tiếp thay vì đợi background loop
engine._generate_autonomous_goal()

print("\n--- Hoàn tất Test ---")
