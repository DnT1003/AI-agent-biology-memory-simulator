import time
from core.engine.cognitive_engine import CognitiveEngine
from colorama import Fore, Style

def test_llm_reading_autonomy():
    print(f"{Fore.CYAN}--- TEST: LLM READING AUTONOMY ---{Style.RESET_ALL}")
    engine = CognitiveEngine()
    
    # Test case: User tells Aura they are busy
    print(f"\n{Fore.YELLOW}Scenario 1: User is busy...{Style.RESET_ALL}")
    user_input = "Tớ phải đi làm đây, vài tiếng nữa quay lại nhé. Aura ở nhà ngoan nhé."
    engine.interaction_loop(user_input)
    
    # We expect Aura to (hopefully) use ACTION: start_reading or at least acknowledge it.
    # The console output will show the THOUGHT and ACTION if triggered.

    print(f"\n{Fore.YELLOW}Scenario 2: User asks for a specific book...{Style.RESET_ALL}")
    user_input = "Hãy tìm cho tớ truyện 'Dế Mèn Phiêu Lưu Ký' trên docln đi."
    engine.interaction_loop(user_input)
    
    # We expect ACTION: search_novel | Dế Mèn Phiêu Lưu Ký
    
    print(f"\n{Fore.GREEN}--- TEST COMPLETED ---{Style.RESET_ALL}")

if __name__ == "__main__":
    test_llm_reading_autonomy()
