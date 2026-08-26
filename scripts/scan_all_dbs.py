import os
import chromadb
import traceback

def scan_all_dbs():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    output_file = os.path.join(os.path.dirname(__file__), "scan_log.txt")
    
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(f"[*] Quét tất cả file chroma.sqlite3 trong: {base_dir}\n")
        
        db_paths = []
        for root, dirs, files in os.walk(base_dir):
            # Bỏ qua các thư mục môi trường ảo và code backup
            if ".venv" in root or ".gemini" in root or "node_modules" in root:
                continue
            if "chroma.sqlite3" in files:
                db_paths.append(root)

        f.write(f"[*] Tìm thấy {len(db_paths)} thư mục DB:\n")
        
        for path in db_paths:
            f.write("\n=========================================\n")
            f.write(f"📂 DB Path: {path}\n")
            try:
                client = chromadb.PersistentClient(path=path)
                collections = client.list_collections()
                if not collections:
                    f.write("   -> Không có collection nào.\n")
                    continue
                    
                for col in collections:
                    f.write(f"   -> Collection: {col.name}\n")
                    col_obj = client.get_collection(col.name)
                    count = col_obj.count()
                    f.write(f"   -> Số bản ghi: {count}\n")
                    
                    if count > 0:
                        results = col_obj.get(include=["metadatas"], limit=10)
                        f.write(f"   -> Preview (Tối đa 10 bản ghi đầu):\n")
                        metas = results.get("metadatas", [])
                        if not metas or metas[0] is None:
                            # Sometimes metadatas is None if not saved
                            f.write("      - [ERROR] Dữ liệu metadata bị trống hoặc None\n")
                            continue
                            
                        for meta in metas:
                            if meta is None: continue
                            
                            # Old DB versions use "data" JSON string
                            m_content = meta.get("content", "N/A")
                            m_type = meta.get("type", "unknown")
                            if "data" in meta:
                                m_content = meta["data"][:100] + " (Old Schema)"
                                
                            if len(m_content) > 150:
                                m_content = m_content[:150] + "..."
                            
                            f.write(f"      - [{m_type}] {m_content}\n")
                            
            except Exception as e:
                f.write(f"   -> Lỗi khi đọc: {e}\n")
                f.write(traceback.format_exc() + "\n")

if __name__ == "__main__":
    scan_all_dbs()
