from components.llm import LLM
from colorama import Fore, Style

class MockEgo:
    def __init__(self, fatigue=0.0):
        self.fatigue = fatigue

def test_hybrid_switching():
    print(f"{Fore.CYAN}--- BẮT ĐẦU KIỂM TRA HYBRID LLM SWITCHING (ISOLATED) ---{Style.RESET_ALL}")
    
    # Khởi tạo Mock Ego
    ego = MockEgo(fatigue=0.1)
    llm = LLM(ego=ego)
    
    # Trường hợp 1: Tỉnh táo (Fatigue thấp)
    print(f"\n{Fore.YELLOW}1. Trạng thái: TỈNH TÁO (Fatigue={ego.fatigue}){Style.RESET_ALL}")
    print("Dự kiến: Sử dụng Gemini Cloud.")
    try:
        response = llm.generate_text("Ai là người tạo ra bạn?")
        print(f"Aura: {response}")
    except Exception as e:
        print(f"Lỗi gọi Gemini (có thể do mạng): {e}")
    
    # Trường hợp 2: Mệt mỏi (Fatigue cao)
    ego.fatigue = 0.8
    print(f"\n{Fore.YELLOW}2. Trạng thái: MỆT MỎI (Fatigue={ego.fatigue}){Style.RESET_ALL}")
    print("Dự kiến: Hệ thống báo mệt mỏi và dùng Local LLM (Phi-3).")
    response = llm.generate_text("Ai là người tạo ra bạn?")
    print(f"Aura: {response}")

    # Trường hợp 3: JSON Generation khi mệt
    print(f"\n{Fore.YELLOW}3. Kiểm tra JSON khi mệt mỏi...{Style.RESET_ALL}")
    res_json = llm.generate_json("Trả về JSON tên và tuổi của bạn.")
    print(f"Kết quả JSON: {res_json}")


if __name__ == "__main__":
    test_hybrid_switching()
