import torch
import spacy
from core.gpu_config import setup_gpu
from core.local_perception import LocalPerception
from core.world_graph import WorldGraph
from colorama import Fore, Style

def test_gpu_optimization():
    print(f"{Fore.CYAN}--- BẮT ĐẦU KIỂM TRA TỐI ƯU HÓA GPU (PHASE 12) ---{Style.RESET_ALL}")
    
    # 1. Setup GPU với giới hạn 4GB
    success = setup_gpu(vram_limit_gb=4.0)
    if not success:
        print(f"{Fore.RED}CUDA không khả dụng hoặc lỗi setup.{Style.RESET_ALL}")
        return

    # 2. Kiểm tra thông tin Memory
    total_mem = torch.cuda.get_device_properties(0).total_memory / (1024**3)
    print(f"GPU: {torch.cuda.get_device_name(0)}")
    print(f"Tổng VRAM vật lý: {total_mem:.2f} GB")
    
    # 3. Load LocalPerception (RoBERTa)
    print("\n[STEP 1] Loading LocalPerception (RoBERTa) on CUDA...")
    lp = LocalPerception()
    lp.analyze("Testing GPU performance and tensor cores.")
    
    # 4. Load WorldGraph (spaCy Transformers)
    print("\n[STEP 2] Loading WorldGraph (spaCy Transformers) on CUDA...")
    wg = WorldGraph(filepath="outputs/test_gpu_graph.json")
    if wg.nlp:
        # Kiểm tra xem spaCy có đang dùng GPU không
        if spacy.prefer_gpu():
             print(f"{Fore.GREEN}✅ spaCy đang sử dụng GPU.{Style.RESET_ALL}")
        else:
             print(f"{Fore.YELLOW}⚠️ spaCy đang chạy trên CPU (mặc dù đã yêu cầu GPU).{Style.RESET_ALL}")
        
    # 5. Kiểm tra mức sử dụng VRAM hiện tại
    allocated = torch.cuda.memory_allocated(0) / (1024**2)
    reserved = torch.cuda.memory_reserved(0) / (1024**2)
    print(f"\n[STATISTICS]")
    print(f"VRAM Allocated: {allocated:.2f} MB")
    print(f"VRAM Reserved: {reserved:.2f} MB")
    
    if reserved <= 4096:
        print(f"{Fore.GREEN}✅ Giới hạn VRAM 4GB hoạt động tốt (Dưới ngưỡng 4096MB).{Style.RESET_ALL}")
    else:
        print(f"{Fore.RED}❌ VRAM vượt quá giới hạn 4GB! Cần kiểm tra lại.{Style.RESET_ALL}")

if __name__ == "__main__":
    test_gpu_optimization()
