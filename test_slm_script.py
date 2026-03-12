import sys
import os
import torch

print(f"Torch Version: {torch.__version__}")
print(f"CUDA Available: {torch.cuda.is_available()}")

sys.path.insert(0, './core/engine/nanogpt')
try:
    from tokenizer import BPETokenizer
    from model import AuraFlashModel
    import slm_params
    
    print("Dependencies imported.")
    
    # Check BPETokenizer
    print("Testing Tokenizer...")
    tok = BPETokenizer()
    vocab_path = './core/engine/nanogpt/vocab.json'
    if os.path.exists(vocab_path):
        tok.load(vocab_path)
        out = tok.encode('Cô ấy')
        print(f"Encode ok: {out}")
    else:
        print(f"Vocab file missing: {vocab_path}")

    # Check Model Architecture
    print("Testing Model Initialization...")
    model = AuraFlashModel(slm_params.vocab_size)
    print("Model instantiated successfully.")
    print(f"Total Params: {sum(p.numel() for p in model.parameters()) / 1e6:.1f} M")
    
except Exception as e:
    print(f"Error occurred: {e}")

print("Test finished.")
