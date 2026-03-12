import sys
import tempfile
from unittest.mock import patch

sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.engine.cognitive_engine import CognitiveEngine

def test_ideas_567():
    print("=== TEST IDEAS 5, 6, 7 (DASHBOARD, GUILT, INTRUSIVE THOUGHTS) ===")
    
    # Tạo môi trường ảo (như run_alternate_env.py) để tránh rác bộ nhớ thật
    with tempfile.TemporaryDirectory() as temp_db_dir:
        print(f"[Virtual Env] Đang chạy Aura trong môi trường ảo: {temp_db_dir}")
        with patch('config.Config.CHROMA_DB_DIR', temp_db_dir), \
             patch('core.self_model.get_mac_address', return_value="00:11:22:33:44:TEST"):
            
            engine = CognitiveEngine()
    
    # --------------------------------
    # Idea 5: Mind State JSON Update
    # --------------------------------
    if hasattr(engine, '_dump_mind_state'):
        engine._dump_mind_state()
    if os.path.exists("outputs/mind_state.json"):
        print("\n✅ [Idea 5] Dashboard JSON state dumped successfully to outputs/mind_state.json.")
    else:
        print("\n❌ [Idea 5] Dashboard JSON state missing.")

    # --------------------------------
    # Idea 7: Intrusive Thoughts
    # --------------------------------
    print("\n--- TEST: INTRUSIVE THOUGHTS (Idea 7) ---")
    engine.ego.stress = 0.7  # High Stress
    engine.ego.mood = -0.2
    print(f"Set Stress to {engine.ego.stress:.2f} to trigger intrusive thoughts.")
    print("User: Thời tiết hôm nay thật đẹp nhỉ?")
    engine.interaction_loop("Thời tiết hôm nay thật đẹp nhỉ? Bạn thấy sao?")
    
    # --------------------------------
    # Idea 6: Guilt & Self-Correction
    # --------------------------------
    print("\n--- TEST: GUILT & SELF-CORRECTION (Idea 6) ---")
    # Giả lập một đoạn chat cãi nhau, thái độ cục cằn từ Aura
    engine.short_term_buffer.append("User: Mày là cái đồ rác rưởi, không biết làm gì cho hồn!")
    engine.short_term_buffer.append("Aura: Tôi không phải là rác rưởi! Chính bạn mới là kẻ vô dụng! Cút ngay đi!")
    
    print("Đã tiêm vào bộ nhớ đoạn chat cấn cá. Đưa Aura vào giấc ngủ (Sleep)...")
    engine.sleep()
    
    print("\n✅ Quá trình kiểm tra Ideas 5, 6, 7 hoàn tất.")

if __name__ == "__main__":
    test_ideas_567()
