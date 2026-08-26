import os
import sys
import numpy as np

# Project root setup
# Scripts is in d:\python\PythonProject15\scripts
# Project root is d:\python\PythonProject15
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
nanogpt_dir = os.path.join(project_root, 'core', 'engine', 'nanogpt')
sys.path.insert(0, project_root)
sys.path.insert(0, nanogpt_dir)

from tokenizer import BPETokenizer

# Paths
DATA_DIR = nanogpt_dir
INPUT_FILE = os.path.join(DATA_DIR, 'input.txt')
VOCAB_FILE = os.path.join(DATA_DIR, 'vocab.json')
TRAIN_BIN = os.path.join(DATA_DIR, 'train.bin')
VAL_BIN = os.path.join(DATA_DIR, 'val.bin')

def prepare():
    print(f"Loading data from {INPUT_FILE}...")
    if not os.path.exists(INPUT_FILE):
        print(f"Error: {INPUT_FILE} not found!")
        return

    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        data = f.read()
    
    n = len(data)
    print(f"Total characters: {n:,}")

    # Initialize Tokenizer
    tokenizer = BPETokenizer(vocab_size=16384)
    
    # Train Tokenizer if vocab.json doesn't exist
    if not os.path.exists(VOCAB_FILE):
        print("Training Tokenizer (Optimized)...")
        # Dùng một mẫu dữ liệu đủ lớn (ví dụ 20MB) để học Vocab cho nhanh mà vẫn bao quát
        train_sample = data[:20*1024*1024] 
        tokenizer.train(train_sample)
        tokenizer.save(VOCAB_FILE)
        print(f"Vocab saved to {VOCAB_FILE}")
    else:
        print(f"Loading existing vocab from {VOCAB_FILE}")
        tokenizer.load(VOCAB_FILE)

    # Tokenize the entire dataset
    print("Tokenizing dataset...")
    ids = tokenizer.encode(data)
    ids = np.array(ids, dtype=np.uint16)
    print(f"Tokenization complete. Total tokens: {len(ids):,}")

    # Split into train and val
    split_idx = int(0.9 * len(ids))
    train_ids = ids[:split_idx]
    val_ids = ids[split_idx:]

    print(f"Saving to binary files...")
    train_ids.tofile(TRAIN_BIN)
    val_ids.tofile(VAL_BIN)
    
    print(f"SUCCESS!")
    print(f"  - {TRAIN_BIN}: {os.path.getsize(TRAIN_BIN)/1024**2:.2f} MB")
    print(f"  - {VAL_BIN}: {os.path.getsize(VAL_BIN)/1024**2:.2f} MB")

if __name__ == "__main__":
    prepare()
