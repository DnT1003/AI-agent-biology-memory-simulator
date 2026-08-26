"""
convert_docx_to_txt.py
Chuyển đổi file DOCX sang TXT và đưa vào folder nanogpt/input.txt để train SLM.
Chạy trong .venv_aura (Python 3.12).
"""
import os
import sys

# Find the DOCX file
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
docx_file = None
for f in os.listdir(project_root):
    if f.endswith('.docx'):
        docx_file = os.path.join(project_root, f)
        break

if not docx_file:
    print("[ERROR] Khong tim thay file .docx!")
    sys.exit(1)

print(f"[INFO] Tim thay file: {docx_file}")
print(f"[INFO] Kich thuoc: {os.path.getsize(docx_file) / 1024 / 1024:.2f} MB")

# Convert using python-docx - stream paragraph by paragraph (memory efficient)
from docx import Document

out_path = os.path.join(project_root, "core", "engine", "nanogpt", "input.txt")
print(f"[INFO] Xuat ra: {out_path}")

doc = Document(docx_file)
total_paragraphs = len(doc.paragraphs)
print(f"[INFO] Tong so doan van: {total_paragraphs:,}")

char_count = 0
written = 0

with open(out_path, 'w', encoding='utf-8') as f:
    for i, para in enumerate(doc.paragraphs):
        text = para.text.strip()
        if not text:
            continue
        f.write(text + '\n')
        char_count += len(text)
        written += 1
        if i % 500 == 0:
            print(f"  [{i}/{total_paragraphs}] Da xu ly {written} doan, {char_count:,} ky tu...")

print(f"\n[DONE] Hoan tat!")
print(f"  - Tong doan viet: {written:,}")
print(f"  - Tong ky tu: {char_count:,}")
print(f"  - Tuong duong ~{char_count // 4:,} tokens")
print(f"  - Luu tai: {out_path}")

# Show sample
print("\n[SAMPLE - 500 ky tu dau]:")
with open(out_path, encoding='utf-8') as f:
    print(f.read(500))
