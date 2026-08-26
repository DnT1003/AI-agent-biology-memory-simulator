# core/engine/nanogpt/slm_params.py
import torch

# ─── Environment ───
device = 'cuda' if torch.cuda.is_available() else 'cpu'

# ─── Data & Context ───
vocab_size = 8192      # Standardized vocab size
block_size = 512       # Context window (Safe for 6GB VRAM)

# ─── Architecture (Aura-MoE-700M Pocket AI) ───
n_layers = 24          # Match checkpoint layers
d_model = 896          # Match checkpoint d_model
n_heads = 16           # Match checkpoint n_heads
n_kv_heads = 4         # GQA: Grouped Query Attention (4 KV heads tiết kiệm VRAM)

# ─── MoE Settings (Pocket AI - Top 2) ───
n_experts = 8          # Tổng số chuyên gia
top_k = 2              # Số chuyên gia được gọi mỗi lượt (Active Params: ~200M/700M)

# ─── Regularization ───
dropout = 0.1

# ─── Training Hyperparameters ───
learning_rate = 3e-4
max_iters = 5000
eval_interval = 250
eval_iters = 15
warmup_iters = 200
grad_clip = 1.0
batch_size = 4         # Test Batch=4 theo yêu cầu sếp (Nguy cơ rướn sát 5.8GB VRAM)
grad_accum_steps = 8   # Effective batch size = 32 (Tính đạo hàm gom lại)
use_checkpoint = True  # BẮT BUỘC để tiết kiệm VRAM Gradient
