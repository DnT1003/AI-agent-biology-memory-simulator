import subprocess
import time
import os
import sys
import threading
from colorama import Fore, Style, init

def run_services():
    print(f"{Fore.CYAN}[AURA WEB] Khởi động các dịch vụ nền (ChromaDB & GPU)...{Style.RESET_ALL}")
    script_path = os.path.join(os.path.dirname(__file__), 'start_services.ps1')
    
    # Gọi script PowerShell để bật các microservices
    subprocess.run(
        ["powershell.exe", "-ExecutionPolicy", "Bypass", "-File", script_path],
        check=True,
    )
    print(f"{Fore.GREEN}[AURA WEB] Dịch vụ nền đã sẵn sàng!{Style.RESET_ALL}")

def start_engine():
    print(f"{Fore.CYAN}[AURA WEB] Đang tải Neural Engine... (Sẽ mất vài giây để load model){Style.RESET_ALL}")
    
    # Setup GPU (giới hạn VRAM)
    from core.gpu_config import setup_gpu
    setup_gpu(vram_limit_gb=4.0)
    
    # Khởi tạo AI Engine
    from core.engine import CognitiveEngine
    ai = CognitiveEngine()
    
    # Bắt đầu vòng lặp nhận thức ngầm trong một thread riêng
    ai.autonomous.start()
    print(f"{Fore.GREEN}[AURA WEB] Neural Engine đang chạy ngầm!{Style.RESET_ALL}")
    return ai

def main():
    init(autoreset=True)
    
    # 1. Chạy start_services.ps1 để bật backend
    run_services()
    
    # 2. Khởi động AI Engine 
    ai = start_engine()
    
    # 3. Giao diện Web
    print(f"\n{Fore.YELLOW}=================================================={Style.RESET_ALL}")
    print(f"{Fore.GREEN}Aura Web Dashboard đang khởi chạy tại:{Style.RESET_ALL}")
    print(f"{Fore.CYAN}👉 http://127.0.0.1:8050{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}==================================================\n{Style.RESET_ALL}")
    
    # Đảm bảo Engine được lưu bộ nhớ và tắt an toàn khi Uvicorn dừng
    import atexit
    def on_exit():
        print(f"\n{Fore.YELLOW}[AURA WEB] Đang tắt hệ thống và lưu trí nhớ...{Style.RESET_ALL}")
        if hasattr(ai, 'shutdown'):
            ai.shutdown()
        else:
            ai.autonomous.stop()
            ai.memory_ops.sleep()
            
    atexit.register(on_exit)
    
    # Bật Uvicorn Web Server chặn (blocking main thread)
    import uvicorn
    from dashboard.server import app
    uvicorn.run(app, host="127.0.0.1", port=8050)

if __name__ == "__main__":
    main()
