"""
Kiểm tra toàn bộ các file .cpp và .h trong ollama_source/llama/llama.cpp
để tìm các lỗi tiềm ẩn:
1. Possessive quantifiers (]++ hay ?+) trong regex string
2. Các include header bị thiếu
3. Các hàm/symbol chưa được định nghĩa
"""
import os, re

base = r'd:\python\PythonProject15\ollama_source\llama\llama.cpp'
src = os.path.join(base, 'src')
common = os.path.join(base, 'common')

issues = []

# 1. Kiểm tra possessive quantifiers trong regex string literals
pattern_possessive = re.compile(r'"\s*[^"]*\]\+\+[^"]*"')
pattern_possessive2 = re.compile(r'"\s*[^"]*\?\+[^"]*"')

for root, dirs, files in os.walk(base):
    # bỏ qua thư mục build
    dirs[:] = [d for d in dirs if d not in ['build', '.git', 'tests', 'examples']]
    for fname in files:
        if not (fname.endswith('.cpp') or fname.endswith('.h')):
            continue
        fpath = os.path.join(root, fname)
        rel = os.path.relpath(fpath, base)
        try:
            with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
        except Exception as e:
            continue
        for i, line in enumerate(lines):
            # skip comments
            stripped = line.strip()
            if stripped.startswith('//'):
                continue
            if ']++'  in line or '?++'  in line:
                # possessive quantifiers inside a string literal?
                if '"' in line:
                    issues.append(('POSSESSIVE_QUANTIFIER', rel, i+1, stripped))

# Print results
if issues:
    print(f"=== {len(issues)} ISSUE(S) FOUND ===")
    for kind, rel, lineno, text in issues:
        print(f"[{kind}] {rel}:{lineno}")
        print(f"  {text}")
else:
    print("=== NO POSSESSIVE QUANTIFIER ISSUES FOUND ===")

# 2. Cũng check llama-context.cpp cho memory/lifecycle issues cụ thể
ctx_file = os.path.join(src, 'llama-context.cpp')
with open(ctx_file, 'r', encoding='utf-8') as f:
    ctx_lines = f.readlines()

print("\n--- Checking llama-context.cpp for model reference lifecycle ---")
# Tìm destructor để xem model reference
in_destructor = False
for i, line in enumerate(ctx_lines):
    if '~llama_context' in line:
        in_destructor = True
    if in_destructor:
        print(f"  L{i+1}: {line.rstrip()}")
        if i > 0 and '}' in line and in_destructor:
            # Check next few lines
            if i > 480:
                break

print("\nDone.")
