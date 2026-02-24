from colorama import Fore, Style, init
from core.engine import CognitiveEngine
from core.memory import MemoryTrace
from config import Config

# Khởi tạo màu sắc cho Terminal
init(autoreset=True)

if __name__ == "__main__":
    ai = CognitiveEngine()

    print(f"{Fore.CYAN}=== HỆ THỐNG NHẬN THỨC SỐ (DIGITAL COGNITIVE SYSTEM) ==={Style.RESET_ALL}")
    print("Gõ 'sleep' để mô phỏng thời gian trôi qua (AI đi ngủ).")
    print("Gõ 'status' để xem trạng thái nội tại.")
    print("Gõ 'exit' để thoát.\n")

    print("Tải ký ức nền từ cơ sở dữ liệu...")

    while True:
        try:
            u_in = input(f"\n{Fore.WHITE}👤 Bạn: {Style.RESET_ALL}")

            if u_in.lower() in ['exit', 'quit']:
                break
            elif u_in.lower() == 'sleep':
                ai.sleep()
                continue
            elif u_in.lower() == 'status':
                print(f"--- STATUS ---")
                mem_count = len(ai.memory.get_all())
                print(f"Memories: {mem_count} (Infinite)")
                print(f"Mood: {ai.ego.mood:.2f} | Stress: {ai.ego.stress:.2f}")
                print(f"Integrity: {ai.ego.integrity:.2f}")
                print(f"Fatigue: {ai.ego.fatigue:.2f} | Social Need: {ai.ego.social_need:.2f} | Curiosity: {ai.ego.curiosity:.2f}")
                continue

            ai.interaction_loop(u_in)

        except KeyboardInterrupt:
            print("\nĐã thoát.")
            break
        except Exception as e:
            print(f"{Fore.RED}Lỗi hệ thống: {e}{Style.RESET_ALL}")