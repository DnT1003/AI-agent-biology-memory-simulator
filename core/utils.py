import os
import json
import shutil

def atomic_read_json(file_path):
    """Đọc file JSON một cách an toàn."""
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def atomic_write_json(file_path, data):
    """Ghi file JSON một cách nguyên tử (atomic) để tránh file bị rỗng/lỗi khi crash."""
    temp_path = file_path + ".tmp"
    try:
        dirpath = os.path.dirname(file_path)
        if dirpath:
            os.makedirs(dirpath, exist_ok=True)
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        # Đồng bộ dữ liệu xuống đĩa cứng trước khi đổi tên
        # os.fsync(f.fileno()) # Optional: more safety
        shutil.move(temp_path, file_path)
    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise e

def atomic_write_text(file_path, text):
    """Ghi file text một cách nguyên tử."""
    temp_path = file_path + ".tmp"
    try:
        dirpath = os.path.dirname(file_path)
        if dirpath:
            os.makedirs(dirpath, exist_ok=True)
        with open(temp_path, 'w', encoding='utf-8') as f:
            f.write(text)
        shutil.move(temp_path, file_path)
    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise e
