import time
from core.engine.cognitive_engine import CognitiveEngine
from colorama import Fore, Style

def test_busy_reading():
    print(f"{Fore.CYAN}--- TEST: BUSY USER TRIGGER ---{Style.RESET_ALL}")
    engine = CognitiveEngine()
    
    user_input = "Tớ bận đi làm cả ngày hôm nay rồi, không có thời gian chat đâu. Aura ngoan nhé."
    print(f"\n{Fore.YELLOW}User: {user_input}{Style.RESET_ALL}")
    engine.interaction_loop(user_input)
    
    print(f"\n{Fore.GREEN}--- TEST COMPLETED ---{Style.RESET_ALL}")

if __name__ == "__main__":
    test_busy_reading()
