import sys
import atexit
import signal
import threading
import asyncio
from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout
from colorama import Fore, Style, init

from core.engine import CognitiveEngine
from core.memory import MemoryTrace
from core.gpu_config import setup_gpu
from config import Config

# Khởi tạo màu sắc cho Terminal
init(autoreset=True)

# Phase 12: Tối ưu hóa GPU (RTX 3060) và giới hạn VRAM
setup_gpu(vram_limit_gb=4.0)

if __name__ == "__main__":
    ai = CognitiveEngine()
    
    is_shutting_down = False
    # Phase 14: Shutdown coordination Event
    _shutdown_complete = threading.Event()

    def handle_exit():
        global is_shutting_down
        if not is_shutting_down:
            is_shutting_down = True
            print(f"\n{Fore.YELLOW}He thong dang tat...{Style.RESET_ALL}")
            try:
                ai.autonomous.stop()  # Signal background loop to stop
                _shutdown_complete.wait(timeout=5.0)  # Wait for clean exit
                ai.memory_ops.sleep()    # Only save AFTER background thread has stopped
                if hasattr(ai, 'shutdown'): ai.shutdown() # Finalize
            except Exception as e:
                print(f"Loi khi luu tri nho: {e}")

    def signal_handler(signum, frame):
        handle_exit()
        sys.exit(0)


    # Đăng ký atexit cho trường hợp thoát bình thường hoặc sys.exit
    atexit.register(handle_exit)
    
    # Đăng ký signal cho SIGTERM, SIGINT (Ctrl+C)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Cố gắng sử dụng win32api để bắt sự kiện Shutdown/Logoff/Close Window trên Windows
    try:
        import win32api
        def win32_handler(ctrl_type):
            handle_exit()
            return True
        win32api.SetConsoleCtrlHandler(win32_handler, True)
    except ImportError:
        pass

    print(f"{Fore.CYAN}=== HỆ THỐNG NHẬN THỨC SỐ (DIGITAL COGNITIVE SYSTEM) ==={Style.RESET_ALL}")
    print("Gõ 'sleep' để mô phỏng thời gian trôi qua (AI đi ngủ).")
    print("Gõ 'status' để xem trạng thái nội tại.")
    print("Gõ 'exit' để thoát.\n")

    print("Tải ký ức nền từ cơ sở dữ liệu...")

    # Start the agent's background loop in a separate thread
    def _bg_wrapper():
        ai.autonomous.background_loop()
        _shutdown_complete.set()  # Bao hieu da thoat sach se
    
    background_thread = threading.Thread(target=_bg_wrapper, daemon=True)
    background_thread.start()

    async def interactive_loop():
        use_prompt_toolkit = True
        try:
            session = PromptSession(f"\n{Fore.WHITE}👤 Bạn: {Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.YELLOW}⚠️ Không tìm thấy Windows Console chuẩn (có thể đang chạy trong IDE). Fallback sang input() thường.{Style.RESET_ALL}")
            use_prompt_toolkit = False

        reply_task = None
        
        while True:
            try:
                if use_prompt_toolkit:
                    with patch_stdout():
                        u_in = await session.prompt_async()
                else:
                    u_in = await asyncio.to_thread(input, f"\n{Fore.WHITE}👤 Bạn: {Style.RESET_ALL}")
                    
                if getattr(ai.interaction, 'is_interrupted', None) is False and reply_task and not reply_task.done():
                    ai.interaction.is_interrupted = True
                    
                if not u_in.strip():
                    continue
                    
                if u_in.lower() in ['exit', 'quit']:
                    break
                elif u_in.lower() == 'sleep':
                    ai.memory_ops.sleep()
                    continue
                elif u_in.lower() == 'status':
                    print(f"--- STATUS ---")
                    mem_count = len(ai.memory.get_all())
                    print(f"Memories: {mem_count} (Infinite)")
                    print(f"Mood: {ai.ego.mood:.2f} | Stress: {ai.ego.stress:.2f}")
                    print(f"Integrity: {ai.ego.integrity:.2f}")
                    print(f"Fatigue: {ai.ego.fatigue:.2f} | Social Need: {ai.ego.social_need:.2f} | Curiosity: {ai.ego.curiosity:.2f}")
                    continue
                
                # Cập nhật thời điểm người dùng vừa tương tác để reset idle time
                import time
                ai.last_interaction_time = time.time()
                ai.interaction.is_interrupted = False
                
                reply_task = asyncio.create_task(
                    asyncio.to_thread(ai.interaction.interaction_loop, u_in)
                )
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"{Fore.RED}Lỗi hệ thống: {e}{Style.RESET_ALL}")
                break
                
    import time
    ai.last_interaction_time = time.time()
    try:
        asyncio.run(interactive_loop())
    except KeyboardInterrupt:
        print("\nĐã thoát.")
        sys.exit(0)