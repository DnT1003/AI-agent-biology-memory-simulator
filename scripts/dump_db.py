import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from components.vector_store import VectorStore

def check_db():
    output_path = os.path.join(os.path.dirname(__file__), "db_contents.txt")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("[*] Đang kết nối tới VectorStore (Long-term Memory)...\n")
        try:
            vs = VectorStore()
            count = vs.collection.count()
            f.write(f"[+] Total vector count in DB: {count}\n")
            
            records = vs.get_all_metadata()
            f.write(f"[+] Đã lấy được: {len(records)} bản ghi metadata.\n")
            
            for i, mem in enumerate(records):
                _type = getattr(mem, 'type', 'unknown')
                _valence = getattr(mem, 'valence', 0.0)
                _strength = getattr(mem, 'strength', 0.0)
                _content = getattr(mem, 'content', 'None')
                
                f.write(f"\n[Mem #{i+1} | Type: {_type}] (Valence: {_valence:.2f}, Strength: {_strength:.2f})\n")
                f.write(f"  > Nội dung : {_content}\n")
                if hasattr(mem, 'overlays') and mem.overlays:
                     f.write(f"  > Overlays : {mem.overlays}\n")
                if getattr(mem, 'is_flashbulb', False):
                     f.write(f"  > [FLASHBULB MEMORY]\n")
                
        except Exception as e:
            f.write(f"Lỗi khi đọc DB: {e}\n")

if __name__ == "__main__":
    check_db()
