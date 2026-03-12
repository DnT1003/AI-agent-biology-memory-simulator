import os
import sys
import shutil
import json

sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# 1. Tạo môi trường ảo (Mock Config / Memory Path)
test_dir = os.path.join(os.path.dirname(__file__), 'temp_alternate_env')
if not os.path.exists(test_dir):
    os.makedirs(test_dir)

# Override environment variables for ChromaDB to use a temporary directory
os.environ["CHROMA_DB_PATH"] = os.path.join(test_dir, "chroma_db")

# Override device ID to simulate a "stranger's device"
identity_file = "identity.json"
original_identity = None
if os.path.exists(identity_file):
    with open(identity_file, "r") as f:
        original_identity = f.read()

try:
    with open(identity_file, "w") as f:
        json.dump({"override_device_id": "UNKNOWN_TEST_DEVICE_999"}, f)
    
    # 2. Ngắt kết nối các modules với DB cũ và khởi tạo
    from core.engine.cognitive_engine import CognitiveEngine
    print("=== CHẠY KIỂM THỬ TRÊN MÁY LẠ (ALTERNATE ENV) ===")
    
    engine = CognitiveEngine()
    
    # Check if stranger mode activated
    print(f"\n[Environment Check]")
    print(f"Device ID: {engine.ego.owner_device_id}")
    print(f"Is Stranger? {engine.ego.is_stranger}")
    print(f"Current Intimacy: {engine.ego.current_intimacy}")
    print(f"Initial Stress: {engine.ego.stress}")

    # 3. Test Visual Stimuli directly on Interaction Loop
    # We will simulate the user sending an image. Since we don't have a real image, we will mock the LLM
    print("\n[Action] Gửi một bức ảnh đáng sợ cho Aura...")
    
    class MockVisionLLM:
        def generate_text(self, prompt, temperature, image_path=None):
            return '''```json
            {
                "valence": -0.9,
                "arousal": 0.8,
                "description": "Một bóng ma mờ ảo xõa tóc vươn tay từ trong bóng tối"
            }
            ```'''
            
    # Swap LLM briefly for the vision test
    real_llm = engine.llm
    engine.llm = MockVisionLLM()
    
    engine.ego.process_visual_stimuli(engine.llm, "fake_ghost_image.jpg")
    
    print(f"\n[After Scary Image]")
    print(f"Stress: {engine.ego.stress:.2f}")
    print(f"Mood: {engine.ego.mood:.2f}")

    # Restore LLM
    engine.llm = real_llm
    
    print("\n[Action] Nói chuyện với Aura sau khi xem bức ảnh...")
    engine.interaction_loop("Bức ảnh tôi vừa gửi thế nào? Trông sợ không?")

finally:
    # 4. Cleanup
    if original_identity is not None:
        with open(identity_file, "w") as f:
            f.write(original_identity)
    else:
        if os.path.exists(identity_file):
            os.remove(identity_file)
            
    # Don't delete chroma_db immediately so we can inspect if needed, or delete it:
    import shutil
    try:
        shutil.rmtree(test_dir)
        print("\n[Cleanup] Đã dọn dẹp môi trường thử nghiệm.")
    except Exception as e:
        print(f"\n[Cleanup Error] {e}")
