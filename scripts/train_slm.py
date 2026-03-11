"""
train_slm.py  —  Aura-MoE 700M "Pocket AI" Production Training
=======================================================
Environment: .venv_aura (Python 3.12 + torch 2.5.1+cu121)
Command:     .\.venv_aura\Scripts\python.exe scripts/train_slm.py

VRAM Budget (RTX 3060 Laptop = 6GB dedicated):
  - Model Weights (700M bf16)        : ~1.4GB
  - Adam8bit Stores (top_k=2)        : ~0.7GB
  - Activations & Gradients          : ~1.5GB
  Total estimated                    : ~4.0GB - 4.5GB  ← well within 6GB

Architecture verified from session Phase 6:
  - AuraFlashModel: 700M params, MoE 8exp/top2, GQA 16h/4kv, No Bias
  - Tokenizer: BPE
"""
import os, sys, time, json

if sys.stdout and hasattr(sys.stdout, 'reconfigure') and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

os.environ.pop('CURL_CA_BUNDLE', None)
os.environ.pop('REQUESTS_CA_BUNDLE', None)

msvc_path = r"C:\Program Files\Microsoft Visual Studio\2022\Enterprise\VC\Tools\MSVC\14.44.35207\bin\Hostx64\x64"
if os.path.exists(msvc_path) and msvc_path not in os.environ.get('PATH', ''):
    os.environ['PATH'] = msvc_path + os.pathsep + os.environ.get('PATH', '')
    
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
nanogpt_dir = os.path.join(project_root, 'core', 'engine', 'nanogpt')
sys.path.insert(0, project_root)
sys.path.insert(0, nanogpt_dir)

import torch
from colorama import Fore, Style, init
init(autoreset=True)

import config as slm_config

# ─────────────────────────────────────────────────────────────────
# HYPERPARAMETERS — Loaded from nanogpt/config.py
# ─────────────────────────────────────────────────────────────────
BATCH_SIZE     = slm_config.batch_size
BLOCK_SIZE     = slm_config.block_size
MAX_ITERS      = getattr(slm_config, 'max_iters', 5000)
EVAL_INTERVAL  = getattr(slm_config, 'eval_interval', 250)
LEARNING_RATE  = 5e-5   # Hạ LR để tránh nhiễu Gradient (Gradient Bouncing) khi fine-tune tập dữ liệu nhỏ.
GRAD_CLIP      = slm_config.grad_clip
WARMUP_ITERS   = getattr(slm_config, 'warmup_iters', 200)
GRAD_ACCUM_STEPS = slm_config.grad_accum_steps
USE_CHECKPOINT = slm_config.use_checkpoint

CHECKPOINT_DIR  = os.path.join(project_root, 'outputs', 'slm_checkpoints')
CHECKPOINT_PATH = os.path.join(nanogpt_dir, 'aura_moe_700m.pth')
RESUME = os.path.exists(CHECKPOINT_PATH)

device = slm_config.device
os.makedirs(CHECKPOINT_DIR, exist_ok=True)

print(f"\n{Fore.CYAN}{'='*60}")
print(f"  Aura-MoE-700M (Pocket AI) — Production Training")
print(f"{'='*60}{Style.RESET_ALL}")
print(f"  Device  : {device.upper()}")
if device == 'cuda':
    gpu = torch.cuda.get_device_properties(0)
    print(f"  GPU     : {gpu.name}")
    print(f"  VRAM    : {gpu.total_memory/1024**3:.1f} GB total")
print(f"  Resume  : {RESUME}")
print(f"  Batch   : {BATCH_SIZE} x {BLOCK_SIZE} chars")
print(f"  Optimizer: bitsandbytes Adam8bit")
print()

# ─── Load data (Production Binary Path) ───────────────────────────
import numpy as np
train_bin = os.path.join(nanogpt_dir, 'train.bin')
val_bin = os.path.join(nanogpt_dir, 'val.bin')

if os.path.exists(train_bin) and os.path.exists(val_bin):
    print(f"[1/5] Nap du lieu nhi phan (memmap): {train_bin}")
    train_data = np.memmap(train_bin, dtype=np.uint16, mode='r')
    val_data = np.memmap(val_bin, dtype=np.uint16, mode='r')
    
    # Vocab size from config
    vocab_size = slm_config.vocab_size
else:
    print(f"[!] CANH BAO: Khong tim thay file .bin. Vui long chay: python scripts/prepare_data.py")
    # Fallback/Old logic (Optional, but better to enforce binary now)
    sys.exit(1)

def get_batch(split):
    data_ptr = train_data if split == 'train' else val_data
    ix = torch.randint(len(data_ptr) - BLOCK_SIZE, (BATCH_SIZE,))
    
    # Chuyển từ uint16 numpy sang torch long
    x = torch.stack([torch.from_numpy((data_ptr[i:i+BLOCK_SIZE]).astype(np.int64)) for i in ix]).to(device)
    y = torch.stack([torch.from_numpy((data_ptr[i+1:i+BLOCK_SIZE+1]).astype(np.int64)) for i in ix]).to(device)
    return x, y

# ─── Build models ─────────────────────────────────────────────────
import model as model_module
model_module.vocab_size = vocab_size
model_module.train_data = train_data
model_module.val_data   = val_data
model_module.block_size = BLOCK_SIZE

from model import AuraFlashModel

print(f"[3/5] Khoi tao model MoE 700M (Active 200M)...")
flash = AuraFlashModel(vocab_size, use_checkpoint=USE_CHECKPOINT).half().to(device)
total_params = sum(p.numel() for p in flash.parameters())
print(f"      → AuraFlash: {total_params/1e6:.1f}M params | VRAM: {torch.cuda.memory_allocated(0)/1024**3:.2f}GB")

if RESUME:
    try:
        flash.load_state_dict(torch.load(CHECKPOINT_PATH, map_location=device, weights_only=True))
        print(f"      → Resume Flash OK: {CHECKPOINT_PATH}")
    except Exception as e:
        print(f"      → Flash resume failed ({e}), starting fresh")

# Native PyTorch Compile
print(f"[3.5/5] Compiling models with Triton/MSVC...")
if os.name == 'nt':
    print(f"      → Skipped: torch.compile() is not natively supported on Windows (Missing Triton).")
else:
    try:
        flash = torch.compile(flash)
        print(f"      → Compile: SUCCESS")
    except Exception as e:
        print(f"      → Compile: FAILED ({e})")

# ─── Optimizers ───────────────────────────────────────────────────
opt_flash = flash.configure_optimizers(weight_decay=0.1, learning_rate=LEARNING_RATE, betas=(0.9, 0.95), device_type=device)
print(f"[4/5] Optimizer: Fused AdamW + Custom WeightDecay")

def get_lr(step):
    import math
    if step < WARMUP_ITERS:
        return LEARNING_RATE * step / WARMUP_ITERS
    progress = (step - WARMUP_ITERS) / (MAX_ITERS - WARMUP_ITERS)
    return LEARNING_RATE * (0.1 + 0.9 * 0.5 * (1.0 + math.cos(math.pi * progress)))

# ─── Eval ─────────────────────────────────────────────────────────
@torch.no_grad()
def estimate_loss(model):
    model.eval()
    losses = {}
    for split in ['train', 'val']:
        ls = torch.zeros(slm_config.eval_iters)
        for k in range(slm_config.eval_iters):
            X, Y = get_batch(split)
            with torch.amp.autocast('cuda', dtype=torch.bfloat16):
                _, loss, aux_loss = model(X, Y)
            ls[k] = (loss + 0.01 * aux_loss).float().item()
        losses[split] = ls.mean().item()
    model.train()
    return losses

# ─── Training loop ────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"  Training {MAX_ITERS} iters | eval every {EVAL_INTERVAL} | batch={BATCH_SIZE} block={BLOCK_SIZE}")
print(f"{'='*60}\n")

flash.train()
best_val = float('inf')
start = time.time()

for step in range(MAX_ITERS):
    lr = get_lr(step)
    for g in opt_flash.param_groups: g['lr'] = lr

    # Eval + checkpoint (Mỗi 250 bước)
    if step % EVAL_INTERVAL == 0:
        lf = estimate_loss(flash)
        elapsed = time.time() - start
        eta = (elapsed / (step + 1)) * (MAX_ITERS - step) if step > 0 else 0
        vram = torch.cuda.memory_allocated(0) / 1024**3
        print(f"  [{step:5d}/{MAX_ITERS}] 🏆 EVAL: val={lf['val']:.4f} train={lf['train']:.4f} | "
              f"VRAM={vram:.2f}GB | {elapsed/60:.1f}m el | ETA={eta/60:.1f}m")

        if lf['val'] < best_val:
            best_val = lf['val']
            torch.save(flash.state_dict(), CHECKPOINT_PATH)
            bkup = os.path.join(CHECKPOINT_DIR, f"flash_s{step:05d}_v{best_val:.4f}.pth")
            torch.save(flash.state_dict(), bkup)
            print(f"  {Fore.GREEN}✅ Best val={best_val:.4f} saved → {CHECKPOINT_PATH}{Style.RESET_ALL}")

    # ─ Train Flash ─
    Xb, Yb = get_batch('train')
    with torch.amp.autocast('cuda', dtype=torch.bfloat16):
        _, raw_loss, aux_loss = flash(Xb, Yb)
        loss = (raw_loss + 0.01 * aux_loss) / GRAD_ACCUM_STEPS
    loss.backward()
    
    # Logging Nhanh (Mỗi 50 bước)
    if step % 50 == 0 and step % EVAL_INTERVAL != 0:
        elapsed = time.time() - start
        eta = (elapsed / (step + 1)) * (MAX_ITERS - step) if step > 0 else 0
        vram = torch.cuda.memory_allocated(0) / 1024**3
        curr_loss = raw_loss.item()
        curr_aux = aux_loss.item()
        print(f"  [{step:5d}/{MAX_ITERS}] ⚡ train_loss={curr_loss:.4f} | aux={curr_aux:.4f} | "
              f"VRAM={vram:.2f}GB | {elapsed/60:.1f}m el | ETA={eta/60:.1f}m")
        # Aggressive Memory Sweeping to prevent creeping
        torch.cuda.empty_cache()
    
    # Xóaa Tensor rác khỏi VRAM ngay lập tức
    del raw_loss, aux_loss, loss, Xb, Yb
    
    if (step + 1) % GRAD_ACCUM_STEPS == 0:
        torch.nn.utils.clip_grad_norm_(flash.parameters(), GRAD_CLIP)
        opt_flash.step()
        opt_flash.zero_grad(set_to_none=True)
    del loss, Xb, Yb

# ─── Done ─────────────────────────────────────────────────────────
total_time = time.time() - start
print(f"\n{Fore.GREEN}{'='*60}")
print(f"  Training HOAN TAT!")
print(f"  Best val loss  : {best_val:.4f}")
print(f"  Checkpoint     : {CHECKPOINT_PATH}")
print(f"  Tong thoi gian : {total_time/60:.1f} phut ({total_time/3600:.2f} gio)")
print(f"{'='*60}{Style.RESET_ALL}")

print(f"\n[5/5] Sample generation (Flash):")
flash.eval()
with torch.no_grad(), torch.amp.autocast('cuda', dtype=torch.bfloat16):
    ctx = torch.tensor(encode("Cô ấy"), dtype=torch.long, device=device).unsqueeze(0)
    out = flash.generate(ctx, max_new_tokens=200)
print(decode(out[0].tolist()))
