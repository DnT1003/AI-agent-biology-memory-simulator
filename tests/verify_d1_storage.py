import sys
import os
from unittest.mock import MagicMock, patch
from colorama import Fore, Style

# Mock modules
sys.modules['core.world_graph'] = MagicMock()
sys.modules['core.local_perception'] = MagicMock()
sys.modules['core.tools'] = MagicMock()
sys.modules['components.reader'] = MagicMock()

from core.engine.cognitive_engine import CognitiveEngine
from config import Config

def test_storage_pressure():
    print(f"{Fore.CYAN}--- KIỂM CHỨNG STORAGE PRESSURE (D1) ---{Style.RESET_ALL}")
    
    # 1. Setup Engine
    mock_llm = MagicMock()
    mock_embedder = MagicMock()
    engine = CognitiveEngine(llm=mock_llm, embedder=mock_embedder)
    
    # 2. Thiết lập trạng thái ban đầu
    engine.ego.stress = 0.5
    original_stress = engine.ego.stress
    
    # Giảm MAX_STORAGE_SIZE xuống cực thấp để test áp lực
    Config.MAX_STORAGE_SIZE = 100 # 100 bytes
    
    # 3. Chạy cognitive_tick
    print(f"\n[STEP] Chạy cognitive_tick với bộ nhớ giả lập 'đầy'...")
    
    # Mock os.path.exists và os.scandir để giả lập thư mục DB lớn
    with patch('os.path.exists', return_value=True), \
         patch('os.scandir') as mock_scandir:
        
        # Giả lập 1 file 200MB (200 * 1024 * 1024 bytes)
        mock_file = MagicMock()
        mock_file.is_file.return_value = True
        mock_file.is_dir.return_value = False
        mock_file.stat.return_value.size = 200 * 1024 * 1024
        
        mock_scandir.return_value.__enter__.return_value = [mock_file]
        
        engine.cognitive_tick(dt=30.0)
        
    # 4. Kiểm tra kết quả
    new_stress = engine.ego.stress
    print(f"  Stress ban đầu: {original_stress:.2f}")
    print(f"  Stress hiện tại: {new_stress:.2f}")
    
    if new_stress > original_stress:
        print(f"  {Fore.GREEN}✅ SUCCESS: Stress đã tăng lên do áp lực bộ nhớ.{Style.RESET_ALL}")
    else:
        print(f"  {Fore.RED}❌ FAILED: Stress không thay đổi mặc dù bộ nhớ quá tải.{Style.RESET_ALL}")
            
    print(f"\n{Fore.CYAN}=== KẾT THÚC KIỂM TRA D1 ==={Style.RESET_ALL}")

if __name__ == "__main__":
    test_storage_pressure()
