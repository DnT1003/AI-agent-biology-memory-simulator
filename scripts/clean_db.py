import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from components.vector_store import VectorStore
from colorama import Fore, Style

def clean_db():
    print(f"[*] Đang dọn dẹp DB chính, chỉ giữ lại Flashbulb Memory...")
    try:
        vs = VectorStore()
        
        records = vs.get_all_metadata()
        if not records:
            print("DB trống rỗng, không cần xóa.")
            return
            
        ids_to_delete = []
        for i, mem in enumerate(records):
            is_flashbulb = getattr(mem, 'is_flashbulb', False)
            if not is_flashbulb:
                ids_to_delete.append(mem.id)
                print(f"  -> Xóa bản ghi: [{getattr(mem, 'type', 'unknown')}] {getattr(mem, 'content', 'N/A')[:50]}...")
            else:
                print(f"  🌟 GIỮ LẠI FLASHBULB: [{getattr(mem, 'type', 'unknown')}] {getattr(mem, 'content', 'N/A')[:50]}...")
                
        if ids_to_delete:
            vs.collection.delete(ids=ids_to_delete)
            print(f"{Fore.GREEN}[+] Đã xóa thành công {len(ids_to_delete)} bóng ma ký ức rác dư thừa.{Style.RESET_ALL}")
        else:
            print(f"{Fore.YELLOW}[-] Tất cả ký ức đều là Flashbulb, không có rác cần xóa.{Style.RESET_ALL}")
            
    except Exception as e:
        print(f"{Fore.RED}Lỗi khi dọn dẹp DB: {e}{Style.RESET_ALL}")

if __name__ == "__main__":
    clean_db()
