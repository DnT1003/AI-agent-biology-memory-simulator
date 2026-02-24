import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.engine import CognitiveEngine
from colorama import Fore, Style

print(f"{Fore.CYAN}--- BẮT ĐẦU KIỂM THỬ: ĐỘNG LỰC SINH HỌC & MỆT MỎI ---{Style.RESET_ALL}")

ai = CognitiveEngine()

# Bơm curiosity lên để test khả năng chủ động đặt câu hỏi
ai.ego.curiosity = 0.8
ai.ego.fatigue = 0.7  # Sắp kiệt sức

print(f"\n{Fore.LIGHTBLACK_EX}[STATUS BAN ĐẦU] Fatigue: {ai.ego.fatigue:.2f} | Curiosity: {ai.ego.curiosity:.2f} | Social Need: {ai.ego.social_need:.2f}{Style.RESET_ALL}")

# Turn 1: Xem Aura có hỏi lại người dùng vì Curiosity cao không
print(f"\n{Fore.WHITE}👤 Bạn: Chào Aura, hôm nay tớ hơi mệt, vừa đi về xong.{Style.RESET_ALL}")
ai.interaction_loop("Chào Aura, hôm nay tớ hơi mệt, vừa đi về xong.")
print(f"{Fore.LIGHTBLACK_EX}[STATUS TURN 1] Fatigue: {ai.ego.fatigue:.2f} | Curiosity: {ai.ego.curiosity:.2f} | Social Need: {ai.ego.social_need:.2f}{Style.RESET_ALL}")

# Turn 2: Ép chạy để Fatigue vọt vạch đỏ (0.7 + 0.15 + 0.15 = 1.0) -> Buộc ngủ
print(f"\n{Fore.WHITE}👤 Bạn: Cậu đang làm gì đấy?{Style.RESET_ALL}")
ai.interaction_loop("Cậu đang làm gì đấy?")
print(f"{Fore.LIGHTBLACK_EX}[STATUS TURN 2] Fatigue: {ai.ego.fatigue:.2f} | Curiosity: {ai.ego.curiosity:.2f}{Style.RESET_ALL}")

# Turn 3: Sập nguồn
print(f"\n{Fore.WHITE}👤 Bạn: Alo Aura còn thức không?{Style.RESET_ALL}")
ai.interaction_loop("Alo Aura còn thức không?")
print(f"{Fore.LIGHTBLACK_EX}[STATUS TURN 3] Fatigue: {ai.ego.fatigue:.2f} | Curiosity: {ai.ego.curiosity:.2f}{Style.RESET_ALL}")

print(f"\n{Fore.GREEN}--- KẾT THÚC KIỂM THỬ ---{Style.RESET_ALL}")
