import sys

path = r'd:\python\PythonProject15\ollama_source\llama\llama.cpp\src\llama-vocab.cpp'

with open(path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

line_429 = lines[428]  # 0-indexed: line 429 is index 428
print("Line 429 BEFORE:", repr(line_429))

# Replace possessive quantifier ++ with greedy +
# In the string literal: [^\\s\\p{L}\\p{N}]++ -> [^\\s\\p{L}\\p{N}]+
if ']++' in line_429:
    lines[428] = line_429.replace(']++', ']+', 1)
    print("Line 429 AFTER: ", repr(lines[428]))
    with open(path, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    print("SUCCESS: File saved.")
else:
    print("Pattern ']++' NOT found in line 429.")
    print("Looking for '++' anywhere in line:", '++' in line_429)

# Also check other lines for any remaining possessive quantifiers
print("\nSearching for possessive quantifiers in all lines...")
for i, line in enumerate(lines):
    if ']++' in line or '?+' in line:
        print(f"  Line {i+1}: {repr(line.strip())}")
