"""Quick perplexity-style eval on val.bin.

Usage:
  .\.venv_aura\Scripts\python.exe scripts/eval_slm.py --batches 50

Notes:
- Requires `core/engine/nanogpt/val.bin` and a compatible checkpoint.
- This is a lightweight sanity check, not a full benchmark.
"""

import argparse
import os
import sys
import math

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
nanogpt_dir = os.path.join(project_root, "core", "engine", "nanogpt")

sys.path.insert(0, project_root)
sys.path.insert(0, nanogpt_dir)

import numpy as np
import torch

import config as slm_config
from model import AuraFlashModel


def _load_state(path: str, map_location: str):
    try:
        return torch.load(path, map_location=map_location, weights_only=True)
    except TypeError:
        return torch.load(path, map_location=map_location)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", default=os.path.join(nanogpt_dir, "aura_moe_700m.pth"))
    ap.add_argument("--batches", type=int, default=50)
    ap.add_argument("--batch-size", type=int, default=slm_config.batch_size)
    ap.add_argument("--block-size", type=int, default=slm_config.block_size)
    ap.add_argument("--device", default=slm_config.device)
    ap.add_argument("--seed", type=int, default=1337)
    args = ap.parse_args()

    device = args.device
    device_type = "cuda" if device == "cuda" else "cpu"
    autocast_enabled = device_type == "cuda"

    val_bin = os.path.join(nanogpt_dir, "val.bin")
    if not os.path.exists(val_bin):
        raise SystemExit(f"Missing val.bin: {val_bin}. Run scripts/prepare_data.py")

    if not os.path.exists(args.checkpoint):
        raise SystemExit(f"Missing checkpoint: {args.checkpoint}")

    torch.manual_seed(args.seed)

    val_data = np.memmap(val_bin, dtype=np.uint16, mode="r")

    vocab_size = int(getattr(slm_config, "vocab_size", 16384))
    model_dtype = torch.bfloat16 if device_type == "cuda" else torch.float32

    model = AuraFlashModel(vocab_size, use_checkpoint=False).to(device=device, dtype=model_dtype)
    model.load_state_dict(_load_state(args.checkpoint, device))
    model.eval()

    def get_batch():
        ix = torch.randint(len(val_data) - args.block_size - 1, (args.batch_size,))
        x = torch.stack(
            [
                torch.from_numpy((val_data[i : i + args.block_size]).astype(np.int64))
                for i in ix
            ]
        ).to(device)
        y = torch.stack(
            [
                torch.from_numpy((val_data[i + 1 : i + args.block_size + 1]).astype(np.int64))
                for i in ix
            ]
        ).to(device)
        return x, y

    losses = []
    with torch.no_grad():
        for _ in range(args.batches):
            X, Y = get_batch()
            with torch.amp.autocast(
                device_type, dtype=torch.bfloat16, enabled=autocast_enabled
            ):
                _, loss, aux_loss = model(X, Y)
                total = (loss + 0.01 * aux_loss).float().item()
            losses.append(total)

    mean_loss = sum(losses) / len(losses)
    ppl = math.exp(mean_loss) if mean_loss < 20 else float("inf")

    print(f"batches={args.batches} batch_size={args.batch_size} block_size={args.block_size}")
    print(f"mean_loss={mean_loss:.4f} ppl~={ppl:.2f}")


if __name__ == "__main__":
    main()
