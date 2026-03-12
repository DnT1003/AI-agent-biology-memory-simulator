import torch
import spacy
from core.local_perception import LocalPerception
from core.world_graph import WorldGraph
from components.llm import LLM
from core.self_model import SelfModel
from colorama import Fore, Style
import os

def check_local_models():
    print(f"{Fore.CYAN}=== KIỂM CHỨNG CÁC MÔ HÌNH CỤC BỘ (LOCAL MODELS) ==={Style.RESET_ALL}")
    
    # 1. Kiểm tra CUDA
    cuda_available = torch.cuda.is_available()
    print(f"CUDA Available: {Fore.GREEN if cuda_available else Fore.RED}{cuda_available}{Style.RESET_ALL}")
    if cuda_available:
        print(f"GPU Device: {torch.cuda.get_device_name(0)}")
        print(f"Memory Allocated: {torch.cuda.memory_allocated(0) / 1024**2:.2f} MB")

    # 2. Kiểm tra Local Perception (RoBERTa)
    print(f"\n[1] Kiểm tra Local Perception (RoBERTa):")
    lp = LocalPerception()
    test_text = "I am so happy to see the system working!"
    res = lp.analyze(test_text)
    print(f"  - Phân tích: '{test_text}'")
    print(f"  - Kết quả: {res}")
    if 'confidence' in res and res['confidence'] > 0:
        print(f"  {Fore.GREEN}✅ RoBERTa đang hoạt động.{Style.RESET_ALL}")
    else:
        print(f"  {Fore.YELLOW}⚠️ RoBERTa ĐANG DÙNG FALLBACK (Không có confidence).{Style.RESET_ALL}")

    # 3. Kiểm tra WorldGraph (spaCy Transformers)
    print(f"\n[2] Kiểm tra WorldGraph (spaCy en_core_web_trf):")
    wg = WorldGraph()
    if wg.nlp:
        entities = wg.extract_entities("Elon Musk lives in Texas and works at SpaceX.")
        print(f"  - Thực thể trích xuất: {entities}")
        if entities:
            print(f"  {Fore.GREEN}✅ spaCy Transformers đang hoạt động.{Style.RESET_ALL}")
    else:
        print(f"  {Fore.RED}❌ spaCy model không nạp được.{Style.RESET_ALL}")

    # 4. Kiểm tra Local LLM Switch (Fatigue logic)
    print(f"\n[3] Kiểm tra Hybrid Switch Logic (Local LLM):")
    ego = SelfModel()
    ego.fatigue = 0.8 # Giả lập mệt mỏi
    llm = LLM(ego=ego)
    
    should_use_local = llm._should_use_local()
    print(f"  - Fatigue: {ego.fatigue} -> Should use Local? {Fore.GREEN if should_use_local else Fore.RED}{should_use_local}{Style.RESET_ALL}")
    
    if should_use_local:
        print(f"  {Fore.GREEN}✅ Logic chuyển đổi Hybrid LLM đã sẵn sàng.{Style.RESET_ALL}")

    print(f"\n{Fore.CYAN}=== KẾT THÚC KIỂM TRA ==={Style.RESET_ALL}")

if __name__ == "__main__":
    check_local_models()
