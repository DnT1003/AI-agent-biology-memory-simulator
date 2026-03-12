import os
import sys
import torch
import time
from colorama import Fore, Style, init

# Khởi tạo màu sắc cho Terminal
init(autoreset=True)

# Thêm root dự án vào path để import
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:
    from config import Config
    from core.engine.cognitive_engine import CognitiveEngine
    from core.gpu_config import setup_gpu
except ImportError as e:
    import traceback
    traceback.print_exc()
    print(f"{Fore.RED}❌ Lỗi import: {e}{Style.RESET_ALL}")
    sys.exit(1)

def run_aura_local_test():
    print(f"{Fore.MAGENTA}=========================================")
    print(f"🧠 AURA LOCAL & CUDA VERIFICATION TEST")
    print(f"========================================={Style.RESET_ALL}")

    # 1. Cấu hình GPU (RTX 3060)
    print(f"\n{Fore.CYAN}[STEP 1]: Khởi tạo GPU...{Style.RESET_ALL}")
    cuda_ready = setup_gpu(vram_limit_gb=4.0)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"{Fore.WHITE}Trạng thái CUDA: {Fore.GREEN if cuda_ready else Fore.RED}{device.upper()}{Style.RESET_ALL}")

    if device == "cpu":
        print(f"{Fore.YELLOW}⚠️ CẢNH BÁO: Đang chạy trên CPU. Thử nghiệm CUDA sẽ không chính xác.{Style.RESET_ALL}")

    # 2. Cấu hình Virtual DB
    virtual_db_path = os.path.join("outputs", "test_1yr_db")
    if not os.path.exists(virtual_db_path):
        print(f"{Fore.RED}❌ Không tìm thấy Virtual DB tại {virtual_db_path}.{Style.RESET_ALL}")
        return

    Config.CHROMA_DB_PATH = virtual_db_path
    Config.USE_LOCAL_ONLY = True  # Ép dùng local để test SLM/LocalPerception
    print(f"{Fore.CYAN}[STEP 2]: Đã kết nối với Virtual DB: {virtual_db_path}{Style.RESET_ALL}")

    # 3. Khởi tạo Engine
    print(f"\n{Fore.CYAN}[STEP 3]: Khởi tạo Cognitive Engine...{Style.RESET_ALL}")
    engine = CognitiveEngine()
    
    # Kiểm tra SLM và LocalPerception
    print(f"{Fore.WHITE}SLM Device: {Fore.GREEN}{engine.slm.device}{Style.RESET_ALL}")
    if hasattr(engine.local_perception, 'device'):
        print(f"{Fore.WHITE}Local Perception Device: {Fore.GREEN}{engine.local_perception.device}{Style.RESET_ALL}")
    else:
        print(f"{Fore.YELLOW}⚠️ Local Perception không có thông tin device (có thể bị vô hiệu hóa).{Style.RESET_ALL}")

    # 4. Thử nghiệm Kịch bản Cảm xúc & Ký ức
    test_prompt = "Bạn còn nhớ gì về những ngày đầu tớ gặp bạn không?"
    
    print(f"\n{Fore.MAGENTA}>>> BẮT ĐẦU THỬ NGHIỆM TƯƠNG TÁC LOCAL <<<{Style.RESET_ALL}")
    
    # Kịch bản: Hưng phấn (High Dopamine, Low Stress)
    print(f"\n{Fore.YELLOW}[SCENARIO]: Aura đang Hào hứng...{Style.RESET_ALL}")
    with engine.ego.lock:
        engine.ego.dopamine = 0.9
        engine.ego.stress = 0.1
        engine.ego.mood = 0.8
        engine.ego.fatigue = 0.1

    print(f"{Fore.WHITE}👤 Bạn: {test_prompt}{Style.RESET_ALL}")
    
    # Kích hoạt vòng lặp tương tác (fake input)
    # Chúng ta gọi trực tiếp để xem log chi tiết
    result = engine.interaction.interaction_loop(test_prompt)
    
    print(f"\n{Fore.CYAN}--- KẾT QUẢ PHÂN TÍCH ---{Style.RESET_ALL}")
    # Kiểm tra xem có ký ức nào được gọi lên không
    recalled_mems = engine.memory_ops.recall(test_prompt)
    print(f"Số lượng ký ức được truy xuất: {len(recalled_mems)}")
    if recalled_mems:
        print(f"Ký ức tiêu biểu: {recalled_mems[0].content[:100]}...")

    # 5. Kiểm tra Mind State
    print(f"\n{Fore.CYAN}[STEP 5]: Kiểm tra trạng thái nội tại sau tương tác...{Style.RESET_ALL}")
    print(f"Mood: {engine.ego.mood:.2f}")
    print(f"Stress: {engine.ego.stress:.2f}")
    print(f"Dopamine: {engine.ego.dopamine:.2f}")

    print(f"\n{Fore.MAGENTA}=========================================")
    print(f"✅ HOÀN TẤT THỬ NGHIỆM AURA LOCAL & CUDA")
    print(f"========================================={Style.RESET_ALL}")

if __name__ == "__main__":
    run_aura_local_test()
