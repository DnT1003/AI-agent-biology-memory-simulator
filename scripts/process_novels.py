import os
import re
from docx import Document
from pypdf import PdfReader
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup

# Đường dẫn
NOVEL_DIR = r"d:\python\PythonProject15\novel"
INPUT_FILE = r"d:\python\PythonProject15\core\engine\nanogpt\input.txt"
TEMP_FILE = r"d:\python\PythonProject15\core\engine\nanogpt\input_new.txt"

def is_vietnamese(text):
    # Dấu tiếng Việt cơ bản
    vn_chars = re.compile(r'[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]', re.IGNORECASE)
    # Đếm số lượng ký tự tiếng Việt
    vn_count = len(vn_chars.findall(text))
    # Đếm tổng số ký tự chữ cái
    alpha_count = len(re.findall(r'[a-zA-Z]', text))
    
    if alpha_count == 0: return False
    # Nếu tỷ lệ ký tự có dấu > 0.5% thì khả năng cao là tiếng Việt (ngưỡng rất thấp để tránh loại bỏ nhầm)
    ratio = vn_count / alpha_count
    return ratio > 0.005

def clean_text(text):
    # Loại bỏ khoảng trắng thừa
    text = re.sub(r'\n\s*\n', '\n\n', text)
    text = re.sub(r' +', ' ', text)
    return text.strip()

def extract_txt(path):
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        return f.read()

def extract_docx(path):
    doc = Document(path)
    return "\n".join([para.text for para in doc.paragraphs])

def extract_pdf(path):
    reader = PdfReader(path)
    text = ""
    for page in reader.pages:
        text += page.extract_text() + "\n"
    return text

def extract_epub(path):
    book = epub.read_epub(path)
    chapters = []
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            soup = BeautifulSoup(item.get_content(), 'html.parser')
            chapters.append(soup.get_text())
    return "\n".join(chapters)

def process_all():
    # Các file cụ thể sếp yêu cầu
    target_files = [
        "Lan Kha Ki Duyen - Chan Phi Su.pdf",
        "Quỷ Bí Chi Chủ - Mực Thích Lặn Nước.pdf",
        "Túc Mệnh Chi Hoàn - Mực Thích Lặn Nước.pdf"
    ]
    
    print(f"Bắt đầu bổ sung {len(target_files)} bộ truyện khổng lồ vào dữ liệu...")

    for filename in target_files:
        path = os.path.join(NOVEL_DIR, filename)
        if not os.path.exists(path):
            print(f"   [!] Không tìm thấy file: {filename}")
            continue

        ext = os.path.splitext(filename)[1].lower()
        
        try:
            content = ""
            if ext == '.pdf':
                content = extract_pdf(path)
            elif ext == '.epub':
                content = extract_epub(path)
            elif ext == '.docx':
                content = extract_docx(path)
            else:
                content = extract_txt(path)
            
            if content:
                # KIỂM TRA NGÔN NGỮ (Cho chắc chắn)
                if is_vietnamese(content[:5000]):
                    print(f"-> Chấp nhận & Đang ghi: {filename}")
                    separator = f"\n\n--- [BẮT ĐẦU TRUYỆN: {filename.upper()}] ---\n\n"
                    
                    # Ghi append trực tiếp để tiết kiệm RAM thay vì load cả file 40MB
                    with open(INPUT_FILE, 'a', encoding='utf-8') as f:
                        f.write(separator + clean_text(content) + "\n")
                    print(f"   [OK] Đã thêm xong {filename}")
                else:
                    print(f"-> LOẠI BỎ: {filename} (Không phải tiếng Việt)")
        except Exception as e:
            print(f"   [ERROR] Lỗi khi xử lý {filename}: {e}")

    print(f"\n HOÀN THÀNH BỔ SUNG!")
    print(f" Kích thước file hiện tại: {os.path.getsize(INPUT_FILE) / 1024**2:.2f} MB")

if __name__ == "__main__":
    process_all()
