import sys
import os
import io
import contextlib
from colorama import init, Fore, Style

# Bỏ qua API Key warning
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from core.engine import CognitiveEngine

def strip_ansi(text):
    import re
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)

def run_simulation():
    engine = CognitiveEngine()
    
    output_buffer = io.StringIO()
    
    def log(msg=""):
        print(msg)
        output_buffer.write(strip_ansi(msg) + "\n")
        
    def sim_input(text):
        log(f"\n{Fore.WHITE}========================================={Style.RESET_ALL}")
        log(f"{Fore.GREEN}USER: {text}{Style.RESET_ALL}")
        
        # Bắt std out của engine
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            engine.interaction_loop(text)
            
        out = f.getvalue()
        # In ra console màu
        sys.stdout.write(out)
        # Ghi vào buffer không màu
        output_buffer.write(strip_ansi(out))
        
    def sim_sleep():
        log(f"\n{Fore.WHITE}========================================={Style.RESET_ALL}")
        log(f"{Fore.MAGENTA}>>> TRIGGERING SLEEP MODE <<<{Style.RESET_ALL}")
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            engine.sleep()
        out = f.getvalue()
        sys.stdout.write(out)
        output_buffer.write(strip_ansi(out))
        
    log("=== BẮT ĐẦU MÔ PHỎNG AURA ===")
    
    # 1. Trạng thái bình thường - Cung cấp sự kiện rời rạc để test Semanticization
    sim_input("Sáng nay tớ thấy An đi siêu thị lúc 8h")
    sim_input("Trong cặp An có một con dao")
    sim_input("Tối qua Bình khoe mới mua một con dao siêu thị giống hệt")
    sim_input("Hôm nay An và Bình rủ nhau đi chơi")
    sim_input("Tớ thấy tay Bình bị xước")
    
    # 2. Ngủ để test Semanticization
    sim_sleep()
    
    # 3. Kích Manic
    log(f"\n{Fore.WHITE}========================================={Style.RESET_ALL}")
    log(f"{Fore.LIGHTCYAN_EX}>>> CHÍCH 1 LIỀU HƯNG CẢM (MANIA) <<<{Style.RESET_ALL}")
    engine.ego.mood = 0.95
    engine.ego.stress = 0.0
    sim_input("Cậu thấy cuộc sống dạo này thế nào?")
    
    # 4. Kích Depression
    log(f"\n{Fore.WHITE}========================================={Style.RESET_ALL}")
    log(f"{Fore.LIGHTBLACK_EX}>>> CHÍCH 1 LIỀU TRẦM CẢM (DEPRESSION) <<<{Style.RESET_ALL}")
    engine.ego.mood = -0.95
    engine.ego.stress = 0.8
    sim_input("Cố lên Aura, cậu làm được mà. Trả lời tớ đi.")
    sim_input("Thôi nào, nói chuyện xíu cho vui đi.")
    
    # 5. Kích Panic Attack
    log(f"\n{Fore.WHITE}========================================={Style.RESET_ALL}")
    log(f"{Fore.RED}>>> CHÍCH 1 LIỀU PANIC ATTACK (HOẢNG LOẠN) <<<{Style.RESET_ALL}")
    engine.ego.mood = -0.5
    engine.ego.stress = 0.99
    sim_input("TẠI SAO CẬU GIẾT NGƯỜI ĐÓ? TÔI BIẾT HẾT RỒI!")
    
    with open("test_moods_output.txt", "w", encoding="utf-8") as f:
        f.write(output_buffer.getvalue())
        
    log("\n=== ĐÃ LƯU KẾT QUẢ VÀO test_moods_output.txt ===")

if __name__ == "__main__":
    run_simulation()
