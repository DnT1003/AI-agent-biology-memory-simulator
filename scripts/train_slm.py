"""
train_slm.py  —  Aura-Flash 1.28B Production Training
=======================================================
Environment: .venv_aura (Python 3.12 + torch 2.5.1+cu121)
Command:     .\.venv_aura\Scripts\python.exe scripts/train_slm.py

VRAM Budget (RTX 3060 Laptop = 6GB dedicated):
  - gpu_service.py (RoBERTa running) : ~484MB
  - Flash model fp16                 : ~2.46GB
  - Tiny model fp16                  : ~70MB
  - Adam8bit stores                  : ~0.6GB (8-bit, no fp32 copy!)
  - Activations (batch=4, block=512) : ~1.5GB
  Total estimated                    : ~5.1GB  ← well within 6GB

Architecture verified from session fc6fb02b:
  - AuraFlashModel: 1.28B params, MoE 8exp/top2, GQA 16h/4kv, RoPE, Ring Blockwise
  - AuraTinyModel:  ~30M params (Speculative Decoding draft model)
  - Tokenizer:      char-level from input.txt (Vietnamese novel corpus)
"""
import os, sys, time, json

os.environ.pop('CURL_CA_BUNDLE', None)
os.environ.pop('REQUESTS_CA_BUNDLE', None)
# Removed expandable_segments as it's unsupported on this platform

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
nanogpt_dir = os.path.join(project_root, 'core', 'engine', 'nanogpt')
sys.path.insert(0, project_root)
sys.path.insert(0, nanogpt_dir)

import torch
from colorama import Fore, Style, init
init(autoreset=True)

# ─────────────────────────────────────────────────────────────────
# HYPERPARAMETERS — Optimizing for full 6GB VRAM usage
# ─────────────────────────────────────────────────────────────────
BATCH_SIZE     = 8      # Tăng lên 8 nhờ Gradient Checkpointing
BLOCK_SIZE     = 512    # Context window súc tích
MAX_ITERS      = 5000   # Chế độ Long-run: 5000 bước huấn luyện
EVAL_INTERVAL  = 250    # Đánh giá mỗi 250 bước để tối ưu tốc độ
LEARNING_RATE  = 3e-4
GRAD_CLIP      = 1.0
WARMUP_ITERS   = 200
USE_CHECKPOINT = True   # Kích hoạt Gradient Checkpointing để tiết kiệm VRAM cực đại

CHECKPOINT_DIR  = os.path.join(project_root, 'outputs', 'slm_checkpoints')
CHECKPOINT_PATH = os.path.join(nanogpt_dir, 'aura_flash_v5.pth')
TINY_CKPT_PATH  = os.path.join(nanogpt_dir, 'aura_tiny_v5.pth')
RESUME = os.path.exists(CHECKPOINT_PATH)

device = 'cuda' if torch.cuda.is_available() else 'cpu'
os.makedirs(CHECKPOINT_DIR, exist_ok=True)

print(f"\n{Fore.CYAN}{'='*60}")
print(f"  Aura-Flash 1.28B — Production Training")
print(f"{'='*60}{Style.RESET_ALL}")
print(f"  Device  : {device.upper()}")
if device == 'cuda':
    gpu = torch.cuda.get_device_properties(0)
    print(f"  GPU     : {gpu.name}")
    print(f"  VRAM    : {gpu.total_memory/1024**3:.1f} GB total")
    free_now = (gpu.total_memory - torch.cuda.memory_reserved(0)) / 1024**3
    print(f"  Free    : {free_now:.2f} GB (excluding other processes)")
print(f"  Resume  : {RESUME}")
print(f"  Batch   : {BATCH_SIZE} x {BLOCK_SIZE} chars")
print(f"  Optimizer: bitsandbytes Adam8bit (no GradScaler needed)")
print()

# ─── Load data ────────────────────────────────────────────────────
input_path = os.path.join(nanogpt_dir, 'input.txt')
print(f"[1/5] Doc du lieu: {input_path}")
with open(input_path, 'r', encoding='utf-8') as f:
    text = f.read()
print(f"      → {len(text):,} ky tu | ~{len(text)//4:,} tokens")

# ─── Vocab ────────────────────────────────────────────────────────
vocab_path = os.path.join(nanogpt_dir, 'vocab.json')
if os.path.exists(vocab_path):
    with open(vocab_path, encoding='utf-8') as f:
        vdata = json.load(f)
    stoi = vdata['stoi']
    itos = {int(k): v for k, v in vdata['itos'].items()}
    vocab_size = vdata['vocab_size']
    print(f"[2/5] Nap vocab: {vocab_size} unique chars")
else:
    chars = sorted(set(text))
    vocab_size = len(chars)
    stoi = {ch: i for i, ch in enumerate(chars)}
    itos = {i: ch for i, ch in enumerate(chars)}
    with open(vocab_path, 'w', encoding='utf-8') as f:
        json.dump({'stoi': stoi, 'itos': {k: v for k, v in itos.items()}, 'vocab_size': vocab_size}, f, ensure_ascii=False)
    print(f"[2/5] Build vocab moi: {vocab_size} chars -> luu vocab.json")

encode = lambda s: [stoi[c] for c in s if c in stoi]
decode = lambda l: ''.join([itos[i] for i in l])

data = torch.tensor(encode(text), dtype=torch.long)
n = int(0.9 * len(data))
train_data, val_data = data[:n], data[n:]
print(f"      → {len(train_data):,} train | {len(val_data):,} val tokens")

def get_batch(split):
    d = train_data if split == 'train' else val_data
    if len(d) <= BLOCK_SIZE:
        return (torch.zeros(BATCH_SIZE, BLOCK_SIZE, dtype=torch.long, device=device),
                torch.zeros(BATCH_SIZE, BLOCK_SIZE, dtype=torch.long, device=device))
    ix = torch.randint(len(d) - BLOCK_SIZE, (BATCH_SIZE,))
    x = torch.stack([d[i:i+BLOCK_SIZE] for i in ix]).to(device)
    y = torch.stack([d[i+1:i+BLOCK_SIZE+1] for i in ix]).to(device)
    return x, y

# ─── Build models ─────────────────────────────────────────────────
import model as model_module
model_module.vocab_size = vocab_size
model_module.train_data = train_data
model_module.val_data   = val_data
model_module.block_size = BLOCK_SIZE

from model import AuraFlashModel, AuraTinyModel

print(f"[3/5] Khoi tao models...")
# Kích hoạt use_checkpoint=True để AuraFlash có thể train 1.28B trên 6GB
flash = AuraFlashModel(vocab_size, use_checkpoint=USE_CHECKPOINT).half().to(device)
total_params = sum(p.numel() for p in flash.parameters())
print(f"      → AuraFlash: {total_params/1e6:.1f}M params | VRAM: {torch.cuda.memory_allocated(0)/1024**3:.2f}GB")
print(f"      → Gradient Checkpointing: {'BAT' if USE_CHECKPOINT else 'TAT'}")

tiny = AuraTinyModel(vocab_size).half().to(device)
tiny_params = sum(p.numel() for p in tiny.parameters())
print(f"      → AuraTiny:  {tiny_params/1e6:.1f}M params | VRAM: {torch.cuda.memory_allocated(0)/1024**3:.2f}GB")

if RESUME:
    try:
        flash.load_state_dict(torch.load(CHECKPOINT_PATH, map_location=device, weights_only=True))
        print(f"      → Resume Flash OK: {CHECKPOINT_PATH}")
    except Exception as e:
        print(f"      → Flash resume failed ({e}), starting fresh")
    if os.path.exists(TINY_CKPT_PATH):
        try:
            tiny.load_state_dict(torch.load(TINY_CKPT_PATH, map_location=device, weights_only=True))
            print(f"      → Resume Tiny OK: {TINY_CKPT_PATH}")
        except Exception as e:
            print(f"      → Tiny resume failed ({e})")

# ─── Optimizers ───────────────────────────────────────────────────
# Adam8bit: does NOT need GradScaler.
# Important: backward() is in fp16 (half), but Adam8bit handles quantized fp32 internally.
import bitsandbytes as bnb
opt_flash = bnb.optim.Adam8bit(flash.parameters(), lr=LEARNING_RATE, weight_decay=0.01)
opt_tiny  = bnb.optim.Adam8bit(tiny.parameters(),  lr=LEARNING_RATE, weight_decay=0.01)
print(f"[4/5] Optimizer: bitsandbytes.Adam8bit (no GradScaler)")

def get_lr(step):
    """Cosine annealing with linear warmup"""
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
        ls = torch.zeros(15)
        for k in range(15):
            X, Y = get_batch(split)
            with torch.amp.autocast('cuda'):
                _, loss = model(X, Y)
            ls[k] = loss.float().item()
        losses[split] = ls.mean().item()
    model.train()
    return losses

# ─── Training loop ────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"  Training {MAX_ITERS} iters | eval every {EVAL_INTERVAL} | batch={BATCH_SIZE} block={BLOCK_SIZE}")
print(f"{'='*60}\n")

flash.train(); tiny.train()
best_val = float('inf')
start = time.time()

for step in range(MAX_ITERS):
    # LR schedule
    lr = get_lr(step)
    for g in opt_flash.param_groups: g['lr'] = lr
    for g in opt_tiny.param_groups:  g['lr'] = lr

    # Eval + checkpoint
    if step % EVAL_INTERVAL == 0:
        lf = estimate_loss(flash)
        lt = estimate_loss(tiny)
        elapsed = time.time() - start
        eta = (elapsed / (step + 1)) * (MAX_ITERS - step) if step > 0 else 0
        vram = torch.cuda.memory_allocated(0) / 1024**3
        print(f"  [{step:5d}/{MAX_ITERS}] Flash val={lf['val']:.4f} train={lf['train']:.4f} | "
              f"Tiny val={lt['val']:.4f} | VRAM={vram:.2f}GB | "
              f"{elapsed/60:.1f}m el | ETA={eta/60:.1f}m")

        if lf['val'] < best_val:
            best_val = lf['val']
            torch.save(flash.state_dict(), CHECKPOINT_PATH)
            torch.save(tiny.state_dict(), TINY_CKPT_PATH)
            bkup = os.path.join(CHECKPOINT_DIR, f"flash_s{step:05d}_v{best_val:.4f}.pth")
            torch.save(flash.state_dict(), bkup)
            print(f"  {Fore.GREEN}✅ Best val={best_val:.4f} saved → {CHECKPOINT_PATH}{Style.RESET_ALL}")

    # ─ Train Flash ─
    Xb, Yb = get_batch('train')
    opt_flash.zero_grad(set_to_none=True)
    with torch.amp.autocast('cuda'):
        _, loss = flash(Xb, Yb)
    loss.backward()
    torch.nn.utils.clip_grad_norm_(flash.parameters(), GRAD_CLIP)
    opt_flash.step()
    del loss, Xb, Yb
    torch.cuda.empty_cache()

    # ─ Train Tiny (every 2 steps) ─
    if step % 2 == 0:
        Xb2, Yb2 = get_batch('train')
        opt_tiny.zero_grad(set_to_none=True)
        with torch.amp.autocast('cuda'):
            _, loss2 = tiny(Xb2, Yb2)
        loss2.backward()
        torch.nn.utils.clip_grad_norm_(tiny.parameters(), GRAD_CLIP)
        opt_tiny.step()
        del loss2, Xb2, Yb2
        torch.cuda.empty_cache()

# ─── Done ─────────────────────────────────────────────────────────
total_time = time.time() - start
print(f"\n{Fore.GREEN}{'='*60}")
print(f"  Training HOAN TAT!")
print(f"  Best val loss  : {best_val:.4f}")
print(f"  Checkpoint     : {CHECKPOINT_PATH}")
print(f"  Tong thoi gian : {total_time/60:.1f} phut ({total_time/3600:.2f} gio)")
print(f"{'='*60}{Style.RESET_ALL}")

# Sample generation
print(f"\n[5/5] Sample generation (Flash):")
flash.eval()
with torch.no_grad(), torch.amp.autocast('cuda'):
    ctx = torch.tensor(encode("Cô ấy"), dtype=torch.long, device=device).unsqueeze(0)
    out = flash.generate(ctx, max_new_tokens=200)
print(decode(out[0].tolist()))
