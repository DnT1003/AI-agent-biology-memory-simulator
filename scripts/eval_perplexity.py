import os
import torch
import numpy as np
import math
import sys
from colorama import Fore, Style, init

init(autoreset=True)

# Path setup
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
nanogpt_dir = os.path.join(project_root, 'core', 'engine', 'nanogpt')
sys.path.insert(0, project_root)
sys.path.insert(0, nanogpt_dir)

import config as slm_config
from model import AuraFlashModel
from tokenizer import BPETokenizer

def eval_perplexity(model_path, data_path, vocab_size, device='cuda'):
    print(f"{Fore.CYAN}--- Aura SLM Perplexity Evaluator ---")
    
    # 1. Load Model
    model = AuraFlashModel(vocab_size)
    model.load_state_dict(torch.load(model_path, map_location=device, weights_only=True))
    model.to(device)
    model.eval()
    print(f"Loaded model from: {model_path}")

    # 2. Load Data
    if not os.path.exists(data_path):
        print(f"{Fore.RED}Error: Data file {data_path} not found.")
        return
    
    data = np.memmap(data_path, dtype=np.uint16, mode='r')
    print(f"Loaded evaluation data: {data_path} ({len(data)} tokens)")

    # 3. Calculation
    batch_size = 4  # Small batch for evaluation
    block_size = slm_config.block_size
    n_batches = min(50, len(data) // block_size)
    
    total_loss = 0
    count = 0
    
    device_type = 'cuda' if 'cuda' in device else 'cpu'
    
    print(f"Evaluating over {n_batches} batches...")
    
    with torch.no_grad():
        for i in range(n_batches):
            # Deterministic evaluation (stride through data)
            start_idx = i * block_size
            if start_idx + block_size + 1 > len(data): break
            
            x = torch.from_numpy(data[start_idx:start_idx+block_size].astype(np.int64)).unsqueeze(0).to(device)
            y = torch.from_numpy(data[start_idx+1:start_idx+block_size+1].astype(np.int64)).unsqueeze(0).to(device)
            
            with torch.amp.autocast(device_type, dtype=torch.bfloat16):
                _, loss, _ = model(x, y)
            
            total_loss += loss.item()
            count += 1

    avg_loss = total_loss / count
    perplexity = math.exp(avg_loss)
    
    print(f"\n{Fore.GREEN}Results:")
    print(f"  Average Cross-Entropy Loss: {avg_loss:.4f}")
    print(f"  Perplexity                : {perplexity:.4f}")
    print("-" * 40)

if __name__ == "__main__":
    MODEL_PATH = os.path.join(nanogpt_dir, "aura_flash_v5.pth")
    DATA_PATH = os.path.join(nanogpt_dir, "val.bin")
    VOCAB_SIZE = slm_config.vocab_size
    DEVICE = 'cuda' if torch.cuda.is_available() else 'cpu'
    
    if not os.path.exists(MODEL_PATH):
        # Try best checkpoint if main pth not found
        checkpoint_dir = os.path.join(project_root, "outputs", "slm_checkpoints")
        if os.path.exists(checkpoint_dir):
            files = [f for f in os.listdir(checkpoint_dir) if f.endswith(".pth")]
            if files:
                MODEL_PATH = os.path.join(checkpoint_dir, sorted(files)[-1])
    
    eval_perplexity(MODEL_PATH, DATA_PATH, VOCAB_SIZE, DEVICE)
