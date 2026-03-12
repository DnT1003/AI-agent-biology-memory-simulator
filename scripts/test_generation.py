import os
import sys
import torch
import time

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
nanogpt_dir = os.path.join(project_root, 'core', 'engine', 'nanogpt')
sys.path.append(nanogpt_dir)

from model import AuraFlashModel
from tokenizer import BPETokenizer

def generate_sample(prompt="Aura mỉm cười và nói:", max_new_tokens=100):
    # Dùng CPU để load model, tránh OOM vì GPU đang bận train
    device = 'cpu'
    print(f"Loading checkpoint into {device.upper()}...")
    
    import json
    
    vocab_path = os.path.join(nanogpt_dir, 'vocab.json')
    if os.path.exists(vocab_path):
        with open(vocab_path, encoding='utf-8') as f:
            vdata = json.load(f)
        stoi = vdata['stoi']
        itos = {int(k): v for k, v in vdata['itos'].items()}
        vocab_size = vdata['vocab_size']
        print(f"Loaded vocab: {vocab_size} unique chars")
    else:
        print("No vocab.json found.")
        return

    encode = lambda s: [stoi[c] for c in s if c in stoi]
    decode = lambda l: ''.join([itos[i] for i in l])

    # Init Model
    model = AuraFlashModel(vocab_size=vocab_size).to(device)
    
    # Load Weights
    ckpt_path = os.path.join(nanogpt_dir, 'aura_flash_v5.pth')
    if not os.path.exists(ckpt_path):
        print(f"No checkpoint found at {ckpt_path}")
        return
        
    checkpoint = torch.load(ckpt_path, map_location=device, weights_only=True)
    if 'model_state_dict' in checkpoint:
        model.load_state_dict(checkpoint['model_state_dict'])
    else:
        model.load_state_dict(checkpoint)
    
    model.eval()
    
    print(f"\nPrompt: {prompt}")
    encoded = encode(prompt)
    x = torch.tensor(encoded, dtype=torch.long, device=device).unsqueeze(0)
    
    print("Generating (can take a minute on CPU)...")
    start = time.time()
    
    with torch.no_grad():
        y = model.generate(x, max_new_tokens=max_new_tokens)
        
    out_text = decode(y[0].tolist())
    elapsed = time.time() - start
    
    print(f"\n{'='*40}")
    print(f"Generated text ({elapsed:.2f}s):\n{out_text}")
    print(f"{'='*40}\n")

if __name__ == "__main__":
    prompt = sys.argv[1] if len(sys.argv) > 1 else "Aura mỉm cười và nói:"
    generate_sample(prompt)
