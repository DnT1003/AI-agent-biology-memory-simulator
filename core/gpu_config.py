try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

try:
    import spacy
    SPACY_AVAILABLE = True
except ImportError:
    SPACY_AVAILABLE = False
import logging
from colorama import Fore, Style

logger = logging.getLogger("gpu_config")

def setup_gpu(vram_limit_gb=4.0):
    """
    Khởi tạo cấu hình GPU cho toàn bộ ứng dụng.
    vram_limit_gb: Mức VRAM tối đa cho phép (GB).
    """
    if not TORCH_AVAILABLE or not torch.cuda.is_available():
        print(f"{Fore.YELLOW}⚠️ [GPU CONFIG]: torch/CUDA không khả dụng. Chạy trên CPU.{Style.RESET_ALL}")
        return False

    try:
        # 1. Tính toán tỉ lệ VRAM (Giả sử RTX 3060 6GB)
        total_mem = torch.cuda.get_device_properties(0).total_memory / (1024**3)
        fraction = min(1.0, vram_limit_gb / total_mem)
        
        # 2. Áp dụng giới hạn VRAM cho tiến trình hiện tại
        torch.cuda.set_per_process_memory_fraction(fraction, 0)
        
        # 3. Kích hoạt GPU cho spaCy (nếu có dùng)
        if SPACY_AVAILABLE:
            try:
                spacy.require_gpu()
                logger.info("spaCy GPU requirement set successfully.")
            except Exception as e:
                logger.warning(f"Could not set spaCy GPU requirement: {e}")
        else:
             logger.debug("spaCy not available, skipping GPU requirement.")

        print(f"{Fore.GREEN}🚀 [GPU CONFIG]: Đã tối ưu hóa RTX 3060. Giới hạn VRAM: {vram_limit_gb}GB ({fraction*100:.1f}%).{Style.RESET_ALL}")
        return True
    except Exception as e:
        logger.error(f"Lỗi cấu hình GPU: {e}")
        return False

# Cấu hình max_memory cho transformers device_map
def get_max_memory_map(vram_limit_gb=4.0):
    if not TORCH_AVAILABLE or not torch.cuda.is_available():
        return None
    return {0: f"{int(vram_limit_gb * 1024)}MiB"}
