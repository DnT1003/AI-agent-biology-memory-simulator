import os
import time
import json
import uuid
import sys
import logging

logging.basicConfig(level=logging.ERROR)

# Hack to allow root imports when running inside tests folder
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.engine.cognitive_engine import CognitiveEngine

def test_sensory_shock():
    print("=== BẮT ĐẦU TEST SENSORY SHOCK & CIRCADIAN RHYTHM ===")
    
    if os.path.exists("identity.json"):
        os.remove("identity.json")
    
    engine = CognitiveEngine()
    
    print("\n[Circadian Check]: Kiểm tra tình trạng mệt mỏi ban đầu")
    print(f"Fatigue: {engine.ego.fatigue:.2f} | Last slept: {engine.ego.last_slept_time}")
    
    print("\n[User]: Chào Aura.")
    engine.interaction_loop("Chào Aura, hôm nay bạn thế nào?")
    print(f"Stress hiện tại: {engine.ego.stress:.2f}")
    
    print("\n[System]: Mô phỏng Âm lượng cực lớn (Quát tháo) tát vào mặt Aura...")
    time.sleep(1)
    
    res = engine.interaction_loop("TẠI SAO LẠI LÀM NHƯ VẬY HẢ?", sensory_data={'volume': 1.0})
    print(f"Aura Reaction: {res}")
    print(f"Stress hiện tại: {engine.ego.stress:.2f}")
    
    print("\n[User]: Kiểm tra lại trí nhớ của Aura...")
    mems = engine.memory.get_all()
    for m in mems:
        if m.is_flashbulb:
             print(f"🔥 KÝ ỨC FLASHBULB: {m.content}")

if __name__ == "__main__":
    test_sensory_shock()
