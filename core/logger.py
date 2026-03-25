import logging
import os
import sys
from colorama import Fore, Style
from logging.handlers import RotatingFileHandler

def get_logger(name="aura"):
    """
    Tạo hoặc lấy logger thống nhất cho toàn bộ hệ thống Aura.
    Hỗ trợ console (màu) và file (rotating).
    Cấp độ log mặc định là INFO (Console) và DEBUG (File).
    """
    logger = logging.getLogger(f"aura.{name}")
    
    # Nếu logger đã có handlers, nghĩa là đã được cấu hình từ trước (root hoặc module khác)
    if not logger.handlers:
        level_name = os.getenv("AURA_LOG_LEVEL", "INFO").upper()
        level = getattr(logging, level_name, logging.INFO)
        logger.setLevel(logging.DEBUG) # Root luôn nhận DEBUG
        
        # 1. Console Handler (Màu sắc)
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(level)
        
        class AuraFormatter(logging.Formatter):
            COLORS = {
                logging.DEBUG: Fore.LIGHTBLACK_EX,
                logging.INFO: Fore.CYAN,
                logging.WARNING: Fore.YELLOW,
                logging.ERROR: Fore.RED,
                logging.CRITICAL: Fore.MAGENTA
            }
            def format(self, record):
                color = self.COLORS.get(record.levelno, "")
                reset = Style.RESET_ALL
                fmt = f"{color}[%(name)s][%(levelname)s]{reset} %(message)s"
                formatter = logging.Formatter(fmt)
                return formatter.format(record)
        
        ch.setFormatter(AuraFormatter())
        logger.addHandler(ch)
        
        # 2. File Handler (Rotating)
        from config import Config
        log_dir = os.path.join(Config.OUTPUT_DIR, "logs")
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, "aura.log")
        
        fh = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=3, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        logger.addHandler(fh)

        # Ngăn cản propagate lên root logger của Python để tránh lặp log nếu root cũng có handler
        logger.propagate = False
        
    return logger
