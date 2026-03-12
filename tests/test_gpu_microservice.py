import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from colorama import Fore, Style, init
from core.local_perception import LocalPerception
from core.engine.slm_core import SLMCore

init(autoreset=True)

def test_gpu_microservice():
    print(f"{Fore.CYAN}--- BẮT ĐẦU KIỂM TRA GPU MICROSERVICE TỪ PYTHON 3.14 ---{Style.RESET_ALL}\n")
    
    print(f"{Fore.YELLOW}1. Kiểm tra LocalPerception (Phân tích cảm xúc){Style.RESET_ALL}")
    lp = LocalPerception()
    tests = [
        "I love you so much!",
        "You are so annoying and stupid.",
        "Tôi cảm thấy rất trống rỗng và mệt mỏi."
    ]
    for text in tests:
        res = lp.analyze(text)
        print(f"Câu: '{text}'")
        print(f"-> Sentiment: {res}\n")

    print(f"{Fore.YELLOW}2. Kiểm tra SLMCore (Suy nghĩ nội tâm){Style.RESET_ALL}")
    slm = SLMCore()
    res2 = slm.generate_thought("Hôm nay trời đẹp quá, tôi muốn", max_tokens=20)
    print(f"Prompt: 'Hôm nay trời đẹp quá, tôi muốn'")
    print(f"-> Phản hồi: {res2}\n")

if __name__ == "__main__":
    test_gpu_microservice()
