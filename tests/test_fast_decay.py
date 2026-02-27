import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.engine import CognitiveEngine

def test_decay():
    print("Khởi tạo Engine...")
    engine = CognitiveEngine()
    
    print("\n--- TRƯỚC KHI NGỦ ---")
    mems = engine.memory.get_all()
    for m in mems[:2]:  # In thử 2 ký ức
        print(f"[{m.id}] Type: {m.type} | Strength: {m.strength:.4f} | Content: {m.content[:50]}...")
        
    print("\n--- GỌI PHÀM SLEEP (Trừ decay và cập nhật DB) ---")
    engine.sleep()
    
    print("\n--- SAU KHI NGỦ (KIỂM TRA CHROMA DB) ---")
    # Khởi tạo lại Engine để đoạt load từ DB lên
    engine2 = CognitiveEngine()
    mems2 = engine2.memory.get_all()
    for m in mems2[:2]:
        print(f"[{m.id}] Type: {m.type} | Strength: {m.strength:.4f} | Content: {m.content[:50]}...")

if __name__ == "__main__":
    test_decay()
