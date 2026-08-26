"""
train_slm.py — Aura-MoE 700M "Pocket AI" Production Training

Environment: .venv_aura (Python 3.12 + torch 2.5.1+cu121)
Command:     .\.venv_aura\Scripts\python.exe scripts/train_slm.py

Notes:
- Requires `core/engine/nanogpt/train.bin`, `val.bin`, and `vocab.json`.
- Generate those with: `scripts/prepare_data.py`.
"""

import os
import sys
import time

if sys.stdout and hasattr(sys.stdout, "reconfigure") and (sys.stdout.encoding or "").lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

os.environ.pop("CURL_CA_BUNDLE", None)
os.environ.pop("REQUESTS_CA_BUNDLE", None)

msvc_path = r"C:\Program Files\Microsoft Visual Studio\2022\Enterprise\VC\Tools\MSVC\14.44.35207\bin\Hostx64\x64"
if os.path.exists(msvc_path) and msvc_path not in os.environ.get("PATH", ""):
    os.environ["PATH"] = msvc_path + os.pathsep + os.environ.get("PATH", "")

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
nanogpt_dir = os.path.join(project_root, "core", "engine", "nanogpt")
sys.path.insert(0, project_root)
sys.path.insert(0, nanogpt_dir)

import numpy as np
import torch
from colorama import Fore, Style, init

init(autoreset=True)

import slm_params as slm_config
from tokenizer import BPETokenizer
from model import AuraFlashModel

# Hyperparameters (from core/engine/nanogpt/config.py)
BATCH_SIZE = slm_config.batch_size
BLOCK_SIZE = slm_config.block_size
MAX_ITERS = getattr(slm_config, "max_iters", 5000)
EVAL_INTERVAL = getattr(slm_config, "eval_interval", 250)
LEARNING_RATE = 5e-5
GRAD_CLIP = slm_config.grad_clip
WARMUP_ITERS = getattr(slm_config, "warmup_iters", 200)
GRAD_ACCUM_STEPS = slm_config.grad_accum_steps
USE_CHECKPOINT = slm_config.use_checkpoint

CHECKPOINT_DIR = os.path.join(project_root, "outputs", "slm_checkpoints")
CHECKPOINT_PATH = os.path.join(nanogpt_dir, "aura_moe_700m.pth")
RESUME = os.path.exists(CHECKPOINT_PATH)

device = slm_config.device
device_type = "cuda" if device == "cuda" else "cpu"
model_dtype = torch.bfloat16 if device_type == "cuda" else torch.float32
os.makedirs(CHECKPOINT_DIR, exist_ok=True)

print(f"\n{Fore.CYAN}{'='*60}")
print("  Aura-MoE-700M (Pocket AI) — Production Training")
print(f"{'='*60}{Style.RESET_ALL}")
print(f"  Device   : {device.upper()}")
if device_type == "cuda":
    gpu = torch.cuda.get_device_properties(0)
    print(f"  GPU      : {gpu.name}")
    print(f"  VRAM     : {gpu.total_memory/1024**3:.1f} GB total")
print(f"  Resume   : {RESUME}")
print(f"  Batch    : {BATCH_SIZE} x {BLOCK_SIZE} tokens")
print(f"  DType    : {model_dtype}")
print()

# Load binary data (memmap)
train_bin = os.path.join(nanogpt_dir, "train.bin")
val_bin = os.path.join(nanogpt_dir, "val.bin")
vocab_path = os.path.join(nanogpt_dir, "vocab.json")

if not (os.path.exists(train_bin) and os.path.exists(val_bin)):
    print("[!] Missing .bin files. Run: python scripts/prepare_data.py")
    sys.exit(1)

if not os.path.exists(vocab_path):
    print(f"[!] Missing vocab.json: {vocab_path}. Run: python scripts/prepare_data.py")
    sys.exit(1)

print(f"[1/5] Loading memmap: {train_bin}")
train_data = np.memmap(train_bin, dtype=np.uint16, mode="r")
val_data = np.memmap(val_bin, dtype=np.uint16, mode="r")

vocab_size = int(slm_config.vocab_size)
tokenizer = BPETokenizer(vocab_size=vocab_size)
tokenizer.load(vocab_path)


def get_batch(split: str):
    data_ptr = train_data if split == "train" else val_data
    ix = torch.randint(len(data_ptr) - BLOCK_SIZE - 1, (BATCH_SIZE,))

    x = torch.stack(
        [torch.from_numpy((data_ptr[i : i + BLOCK_SIZE]).astype(np.int64)) for i in ix]
    ).to(device)
    y = torch.stack(
        [
            torch.from_numpy((data_ptr[i + 1 : i + BLOCK_SIZE + 1]).astype(np.int64))
            for i in ix
        ]
    ).to(device)
    return x, y


print("[3/5] Initializing model...")
flash = AuraFlashModel(vocab_size, use_checkpoint=USE_CHECKPOINT).to(
    device=device, dtype=model_dtype
)
total_params = sum(p.numel() for p in flash.parameters())
vram0 = (torch.cuda.memory_allocated(0) / 1024**3) if device_type == "cuda" else 0.0
print(f"      → AuraFlash: {total_params/1e6:.1f}M params | VRAM: {vram0:.2f}GB")

if RESUME:
    try:
        try:
            state = torch.load(CHECKPOINT_PATH, map_location=device, weights_only=True)
        except TypeError:
            state = torch.load(CHECKPOINT_PATH, map_location=device)
        flash.load_state_dict(state)
        print(f"      → Resume OK: {CHECKPOINT_PATH}")
    except Exception as e:
        print(f"      → Resume failed ({e}), starting fresh")

print("[4/5] Optimizer...")
opt_flash = flash.configure_optimizers(
    weight_decay=0.1,
    learning_rate=LEARNING_RATE,
    betas=(0.9, 0.95),
    device_type=device,
)


def get_lr(step: int):
    import math

    if step < WARMUP_ITERS:
        return LEARNING_RATE * step / max(WARMUP_ITERS, 1)
    progress = (step - WARMUP_ITERS) / max((MAX_ITERS - WARMUP_ITERS), 1)
    return LEARNING_RATE * (0.1 + 0.9 * 0.5 * (1.0 + math.cos(math.pi * progress)))


@torch.no_grad()
def estimate_loss(model):
    model.eval()
    losses = {}
    autocast_enabled = device_type == "cuda"

    for split in ["train", "val"]:
        ls = torch.zeros(slm_config.eval_iters)
        for k in range(slm_config.eval_iters):
            X, Y = get_batch(split)
            with torch.amp.autocast(
                device_type, dtype=torch.bfloat16, enabled=autocast_enabled
            ):
                _, loss, aux_loss = model(X, Y)
            ls[k] = (loss + 0.01 * aux_loss).float().item()
        losses[split] = ls.mean().item()

    model.train()
    return losses


print(f"\n{'='*60}")
print(
    f"  Training {MAX_ITERS} iters | eval every {EVAL_INTERVAL} | batch={BATCH_SIZE} block={BLOCK_SIZE}"
)
print(f"{'='*60}\n")

flash.train()
best_val = float("inf")
start = time.time()
autocast_enabled = device_type == "cuda"

for step in range(MAX_ITERS):
    lr = get_lr(step)
    for g in opt_flash.param_groups:
        g["lr"] = lr

    if step % EVAL_INTERVAL == 0:
        lf = estimate_loss(flash)
        elapsed = time.time() - start
        eta = (elapsed / (step + 1)) * (MAX_ITERS - step) if step > 0 else 0
        vram = (torch.cuda.memory_allocated(0) / 1024**3) if device_type == "cuda" else 0.0
        print(
            f"  [{step:5d}/{MAX_ITERS}] EVAL: val={lf['val']:.4f} train={lf['train']:.4f} | "
            f"VRAM={vram:.2f}GB | {elapsed/60:.1f}m el | ETA={eta/60:.1f}m"
        )

        if lf["val"] < best_val:
            best_val = lf["val"]
            torch.save(flash.state_dict(), CHECKPOINT_PATH)
            bkup = os.path.join(CHECKPOINT_DIR, f"flash_s{step:05d}_v{best_val:.4f}.pth")
            torch.save(flash.state_dict(), bkup)
            print(f"  {Fore.GREEN}✓ Best val={best_val:.4f} saved → {CHECKPOINT_PATH}{Style.RESET_ALL}")

    Xb, Yb = get_batch("train")
    with torch.amp.autocast(device_type, dtype=torch.bfloat16, enabled=autocast_enabled):
        _, raw_loss, aux_loss = flash(Xb, Yb)
        loss = (raw_loss + 0.01 * aux_loss) / GRAD_ACCUM_STEPS

    loss.backward()

    if step % 50 == 0 and step % EVAL_INTERVAL != 0:
        elapsed = time.time() - start
        eta = (elapsed / (step + 1)) * (MAX_ITERS - step) if step > 0 else 0
        vram = (torch.cuda.memory_allocated(0) / 1024**3) if device_type == "cuda" else 0.0
        print(
            f"  [{step:5d}/{MAX_ITERS}] train_loss={raw_loss.item():.4f} | aux={aux_loss.item():.4f} | "
            f"VRAM={vram:.2f}GB | {elapsed/60:.1f}m el | ETA={eta/60:.1f}m"
        )
        if device_type == "cuda":
            torch.cuda.empty_cache()

    del raw_loss, aux_loss, loss

    if (step + 1) % GRAD_ACCUM_STEPS == 0:
        torch.nn.utils.clip_grad_norm_(flash.parameters(), GRAD_CLIP)
        opt_flash.step()
        opt_flash.zero_grad(set_to_none=True)

    del Xb, Yb


total_time = time.time() - start
print(f"\n{Fore.GREEN}{'='*60}")
print("  Training COMPLETE!")
print(f"  Best val loss  : {best_val:.4f}")
print(f"  Checkpoint     : {CHECKPOINT_PATH}")
print(f"  Total time     : {total_time/60:.1f} min ({total_time/3600:.2f} hr)")
print(f"{'='*60}{Style.RESET_ALL}")

print("\n[5/5] Sample generation:")
flash.eval()
with torch.no_grad(), torch.amp.autocast(device_type, dtype=torch.bfloat16, enabled=autocast_enabled):
    ctx = torch.tensor(tokenizer.encode("Cô ấy"), dtype=torch.long, device=device).unsqueeze(0)
    out = flash.generate(ctx, max_new_tokens=200)
print(tokenizer.decode(out[0].tolist()))
