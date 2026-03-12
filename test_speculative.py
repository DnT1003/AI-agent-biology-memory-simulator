import torch
from core.engine.nanogpt.model import AuraFlashModel, AuraTinyModel, speculative_generate

device = 'cuda' if torch.cuda.is_available() else 'cpu'

# 1. Initialize models
vocab_size = 16384
print("Khởi tạo AuraFlashModel (~130M params)...")
flash = AuraFlashModel(vocab_size=vocab_size, use_checkpoint=False).to(device).bfloat16()
print("Khởi tạo AuraTinyModel...")
tiny = AuraTinyModel(vocab_size=vocab_size).to(device).bfloat16()

print("Mô hình khởi tạo thành công. Test Speculative Decoding...")

# 2. Test generation
idx = torch.tensor([[1, 2, 3]], dtype=torch.long, device=device)

with torch.no_grad():
    out_idx = speculative_generate(tiny, flash, idx, max_new_tokens=10, k=3)
    
print(f"Speculative Decoding chạy thành công! Đầu ra shape: {out_idx.shape}")
print(out_idx)
