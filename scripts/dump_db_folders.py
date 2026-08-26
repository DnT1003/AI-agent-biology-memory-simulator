import sys
import os
import chromadb

def check_db_folder(db_path, fname):
    output_path = os.path.join(os.path.dirname(__file__), fname)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"[*] Quét thư mục: {db_path}\n")
        if not os.path.exists(db_path):
            f.write(f"  -> Thư mục không tồn tại!\n")
            return
            
        try:
            client = chromadb.PersistentClient(path=db_path)
            collections = client.list_collections()
            if not collections:
                f.write(f"  -> Không có collection nào trong DB này.\n")
                return
            
            for col in collections:
                f.write(f"  -> Collection name: {col.name}\n")
                col_obj = client.get_collection(col.name)
                count = col_obj.count()
                f.write(f"  -> Count: {count}\n")
                
                if count > 0:
                    results = col_obj.get(include=["metadatas"])
                    if results and results.get("metadatas"):
                        for i, meta in enumerate(results["metadatas"]):
                            m_content = meta.get("content", "N/A")
                            m_type = meta.get("type", "unknown")
                            f.write(f"\n[Mem #{i+1} | {m_type}] {m_content}\n")
                
        except Exception as e:
            f.write(f"Lỗi khi đọc DB: {e}\n")

if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    check_db_folder(os.path.join(base_dir, "outputs", "test_1yr_db"), "db_test1.txt")
    check_db_folder(os.path.join(base_dir, "outputs", "test_resilience_db"), "db_test2.txt")
